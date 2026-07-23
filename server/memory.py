"""Conversation memory management for marketing-agent sessions.

The database keeps the full transcript. This module builds a compact working
context for model calls: long-term marketing profile, compressed older turns,
and a recent sliding window under a rough token budget.
"""
from __future__ import annotations

import json
import re
from typing import Any

from marketing_agent import config
from marketing_agent.conversation import Conversation

from . import db

RECENT_MESSAGE_WINDOW = 12
CONTEXT_TOKEN_BUDGET = 24000
SUMMARY_CHAR_BUDGET = 3200
RECENT_MESSAGE_CHAR_CAP = 5000
# Incidental mentions must recur this many times before promotion. Explicit
# self-declarations (see `Observation.explicit`) bypass this and promote at once.
LONG_TERM_EVIDENCE_THRESHOLD = 3
# How many learned values to keep per multi-valued field once promoted.
LEARNED_MULTI_VALUE_CAP = 8
# Max de-duped values kept per field when rendering/storing a profile.
PROFILE_VALUE_CAP = 12

MARKETING_PROFILE_FIELDS = {
    "role_title": "Role/title",
    "industry": "Industry",
    "company_brand": "Company/brand",
    "products": "Products/services",
    "target_customers": "Target customers",
    "channels": "Preferred channels",
    "tone_preferences": "Tone/style preferences",
    "report_format_preferences": "Report format preferences",
    "kpi_data_preferences": "KPI/data definition preferences",
    "other_preferences": "Other long-term preferences",
}

# Fields that describe a single durable fact — keep only the most recent /
# authoritative value so contradictory learned values cannot pile up.
SINGLE_VALUE_FIELDS = {"role_title", "industry", "company_brand"}

# Old profile keys still accepted on input and folded into the canonical field.
LEGACY_PROFILE_ALIASES = {
    "industry": "industries",
    "target_customers": "audiences",
    "tone_preferences": "tones",
    "report_format_preferences": "deliverables",
}


def build_conversation(session_id: str, user_id: str) -> Conversation | None:
    if db.get_session(session_id, user_id) is None:
        return None
    rows = db.list_messages(session_id)
    summary = _summary_for_rows(session_id, user_id, rows)
    recent_rows = rows[-RECENT_MESSAGE_WINDOW:]

    messages: list[dict[str, Any]] = []
    memory_blocks: list[str] = []
    profile_enabled = db.get_user_memory_settings(user_id).get("long_term_enabled", True)
    profile = merged_profile(user_id) if profile_enabled else {}
    profile_text = _format_profile(profile)
    if profile_text:
        memory_blocks.append(profile_text)
    if summary:
        memory_blocks.append(_memory_block("Conversation summary", summary))
    if memory_blocks:
        messages.append({"role": "user", "content": "\n\n".join(memory_blocks)})

    messages.extend(_sanitize_recent_messages(recent_rows))
    messages = _fit_token_budget(messages, CONTEXT_TOKEN_BUDGET)
    return Conversation(messages=messages)


def update_long_term_marketing_memory(user_id: str, *texts: str) -> dict | None:
    """Record profile evidence from prompt text and return the learned profile.

    Manual profile edits live in their own table and always win at injection
    time; this only feeds the evidence ledger. The learned profile is a pure
    function of (decayed) evidence — dropping evidence forgets the value.
    """
    if not db.get_user_memory_settings(user_id).get("long_term_enabled", True):
        return None

    from . import memory_extraction  # local import avoids an import cycle

    # Feed existing values so the extractor can reuse a canonical form for
    # paraphrases of the same thing (semantic de-duplication).
    known_values: dict[str, list[str]] = {}
    for row in db.list_user_marketing_memory_evidence(user_id):
        field = str(row.get("field") or "")
        value = str(row.get("value") or "").strip()
        if field in MARKETING_PROFILE_FIELDS and value:
            known_values.setdefault(field, []).append(value)

    observations = memory_extraction.extract_observations(
        texts, use_llm=config.memory_llm_extraction_enabled(), known_values=known_values
    )
    triples = [
        (obs.field, obs.value, obs.explicit)
        for obs in observations
        if obs.field in MARKETING_PROFILE_FIELDS and obs.value
    ]
    if not triples:
        return None

    db.add_user_marketing_memory_evidence(user_id, triples)
    db.prune_user_marketing_memory_evidence(user_id, min_count=LONG_TERM_EVIDENCE_THRESHOLD)
    return derive_learned_profile(user_id) or None


def heuristic_observations(texts: tuple[str, ...]) -> list[tuple[str, str, bool]]:
    """Deterministic, offline extraction used as the LLM fallback.

    Structured self-declarations ("我的产品是X" / "product is X") are marked
    explicit; keyword/pattern hits are incidental (``explicit=False``).
    """
    out: list[tuple[str, str, bool]] = []
    keyword = {
        "role_title": _extract_values(texts, _ROLE_PATTERNS),
        "industry": _extract_values(texts, _INDUSTRY_PATTERNS),
        "company_brand": _extract_values(texts, _COMPANY_PATTERNS),
        "products": _extract_values(texts, _PRODUCT_PATTERNS),
        "target_customers": _extract_values(texts, _AUDIENCE_PATTERNS),
        "channels": _extract_values(texts, _CHANNEL_PATTERNS),
        "tone_preferences": _extract_values(texts, _TONE_PATTERNS),
        "report_format_preferences": _extract_values(texts, _DELIVERABLE_PATTERNS),
        "kpi_data_preferences": _extract_values(texts, _KPI_PATTERNS),
    }
    for field, values in keyword.items():
        for value in values:
            out.append((field, value, False))
    for field, values in _extract_structured_observations(texts).items():
        for value in values:
            out.append((field, value, True))
    return out


def derive_learned_profile(user_id: str) -> dict[str, list[str]]:
    """Compute the auto-learned profile from the current evidence ledger.

    A value is promoted only after it has recurred `LONG_TERM_EVIDENCE_THRESHOLD`
    times — a single mention (even an explicit self-declaration) stays in the
    session's short-term memory and does not enter long-term memory, so the two
    layers don't overlap. The ``explicit`` flag no longer fast-tracks promotion;
    it is kept only as a provenance signal and a tie-breaker. Single-valued
    fields keep only the top value (recency/explicit win) so contradictory
    learned facts cannot accumulate; multi-valued fields keep the most
    recent/strongest values up to a cap.
    """
    by_field: dict[str, list[dict]] = {}
    for row in db.list_user_marketing_memory_evidence(user_id):
        if int(row.get("count") or 0) < LONG_TERM_EVIDENCE_THRESHOLD:
            continue
        field = str(row.get("field") or "")
        if field in MARKETING_PROFILE_FIELDS:
            by_field.setdefault(field, []).append(row)

    profile: dict[str, list[str]] = {}
    for field, rows in by_field.items():
        rows.sort(
            key=lambda r: (
                1 if bool(r.get("explicit")) else 0,
                float(r.get("last_seen_at") or 0.0),
                int(r.get("count") or 0),
            ),
            reverse=True,
        )
        cap = 1 if field in SINGLE_VALUE_FIELDS else LEARNED_MULTI_VALUE_CAP
        values: list[str] = []
        for row in rows:
            value = str(row.get("value") or "").strip()
            if value and value not in values:
                values.append(value)
            if len(values) >= cap:
                break
        if values:
            profile[field] = values
    return profile


def merged_profile(user_id: str) -> dict[str, list[str]]:
    """Profile injected into model turns: manual edits override learned values."""
    manual = canonicalize_profile((db.get_user_marketing_memory(user_id) or {}).get("profile") or {})
    learned = derive_learned_profile(user_id)
    out: dict[str, list[str]] = {}
    for field in MARKETING_PROFILE_FIELDS:
        values = manual.get(field) or learned.get(field)
        if values:
            out[field] = values
    return out


def split_values(value: Any) -> list[str]:
    """Split user-entered field input (list or comma/newline string) into a list."""
    if value is None:
        return []
    if isinstance(value, list):
        raw = value
    else:
        raw = str(value).replace("，", ",").replace("\n", ",").split(",")
    out: list[str] = []
    for item in raw:
        text = str(item).strip()
        if text and text not in out:
            out.append(text)
        if len(out) >= PROFILE_VALUE_CAP:
            break
    return out


def canonicalize_profile(profile: dict | None) -> dict[str, list[str]]:
    """Normalize a profile to canonical fields, folding legacy aliases in."""
    profile = profile or {}
    normalized: dict[str, list[str]] = {}
    for field in MARKETING_PROFILE_FIELDS:
        values = split_values(profile.get(field))
        alias = LEGACY_PROFILE_ALIASES.get(field)
        if alias:
            for item in split_values(profile.get(alias)):
                if item not in values:
                    values.append(item)
        if values:
            normalized[field] = values[:PROFILE_VALUE_CAP]
    return normalized


def _summary_for_rows(session_id: str, user_id: str, rows: list[dict]) -> str:
    old_rows = rows[:-RECENT_MESSAGE_WINDOW]
    if not old_rows:
        return ""
    existing = db.get_session_memory_summary(session_id, user_id)
    if existing and int(existing.get("source_message_count") or 0) == len(old_rows):
        return str(existing.get("summary") or "")
    summary = _compress_rows(old_rows)
    db.upsert_session_memory_summary(session_id, user_id, summary, len(old_rows))
    return summary


def _compress_rows(rows: list[dict]) -> str:
    facts: list[str] = []
    user_intents: list[str] = []
    deliverables: list[str] = []
    for row in rows:
        text = _plain_text(row.get("content", ""))
        if not text:
            continue
        clipped = _clip(text, 420)
        role = row.get("role")
        if role == "user":
            user_intents.append(clipped)
        elif _looks_like_deliverable(text):
            deliverables.append(clipped)
        elif len(facts) < 8:
            facts.append(clipped)

    parts: list[str] = []
    if user_intents:
        # Recency-first: keep the most recent user needs so the summary follows
        # topic changes instead of anchoring to a possibly-stale founding goal.
        parts.append("Earlier user needs:\n" + "\n".join(f"- {item}" for item in user_intents[-8:]))
    if deliverables:
        parts.append("Important prior outputs:\n" + "\n".join(f"- {item}" for item in deliverables[-6:]))
    if facts:
        parts.append("Other relevant context:\n" + "\n".join(f"- {item}" for item in facts[-6:]))
    return _clip("\n\n".join(parts), SUMMARY_CHAR_BUDGET)


def _sanitize_recent_messages(rows: list[dict]) -> list[dict[str, Any]]:
    sanitized: list[dict[str, Any]] = []
    for row in rows:
        role = row.get("role")
        if role not in {"user", "assistant"}:
            continue
        text = _plain_text(row.get("content", ""))
        if not text:
            continue
        sanitized.append({"role": role, "content": _clip(text, RECENT_MESSAGE_CHAR_CAP)})
    return sanitized


def _fit_token_budget(messages: list[dict[str, Any]], budget: int) -> list[dict[str, Any]]:
    kept = list(messages)
    while kept and _estimate_tokens(kept) > budget:
        # Preserve memory/profile blocks when possible, drop the oldest ordinary turn.
        drop_index = 0
        if len(kept) > 2 and _is_memory_block(kept[0]) and _is_memory_block(kept[1]):
            drop_index = 2
        elif len(kept) > 1 and _is_memory_block(kept[0]):
            drop_index = 1
        kept.pop(drop_index)
    return kept


def _estimate_tokens(messages: list[dict[str, Any]]) -> int:
    chars = 0
    for message in messages:
        chars += len(str(message.get("role", ""))) + len(_plain_text(message.get("content", "")))
    return max(1, chars // 4)


def _plain_text(content: Any) -> str:
    if isinstance(content, str):
        try:
            parsed = json.loads(content)
        except (TypeError, ValueError):
            return content.strip()
        return _plain_text(parsed)
    if isinstance(content, list):
        chunks: list[str] = []
        for block in content:
            if isinstance(block, dict):
                if block.get("type") == "text" and block.get("text"):
                    chunks.append(str(block["text"]))
                elif block.get("type") == "tool_result" and block.get("content"):
                    chunks.append(_clip(_plain_text(block.get("content")), 900))
            elif hasattr(block, "type") and getattr(block, "type", None) == "text":
                chunks.append(str(getattr(block, "text", "")))
        return "\n\n".join(chunk.strip() for chunk in chunks if chunk and chunk.strip())
    return str(content).strip()


def _memory_block(title: str, body: str) -> str:
    return f"[{title}]\n{body}\n[/ {title}]"


def _format_profile(profile: dict) -> str:
    profile = canonicalize_profile(profile)
    if not profile:
        return ""
    lines = []
    for key, label in MARKETING_PROFILE_FIELDS.items():
        values = profile.get(key)
        if values:
            lines.append(f"- {label}: {', '.join(_as_list(values)[:8])}")
    if not lines:
        return ""
    lines.insert(0, "Use this profile only to fill missing context. If it conflicts with the current user request, the current request takes priority.")
    return _memory_block("Long-term enterprise marketing profile", "\n".join(lines))


def _is_memory_block(message: dict[str, Any]) -> bool:
    content = str(message.get("content", ""))
    return content.startswith("[Long-term enterprise marketing profile]") or content.startswith("[Conversation summary]")


def _clip(text: str, limit: int) -> str:
    clean = re.sub(r"\s+", " ", text).strip()
    if len(clean) <= limit:
        return clean
    return clean[: max(0, limit - 1)].rstrip() + "…"


def _looks_like_deliverable(text: str) -> bool:
    lowered = text.lower()
    return any(token in lowered for token in ("#", "##", "cta", "报告", "文案", "方案", "brief", "post", "copy"))


def _merge_list(existing: Any, discovered: list[str], limit: int = 12) -> list[str]:
    out: list[str] = []
    for value in [*_as_list(existing), *_as_list(discovered)]:
        item = str(value).strip()
        if item and item not in out:
            out.append(item)
        if len(out) >= limit:
            break
    return out


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    return [text] if text else []


def _extract_values(texts: tuple[str, ...], patterns: list[tuple[str, str]]) -> list[str]:
    haystack = "\n".join(text for text in texts if text)
    compact = haystack.replace(" ", "").lower()
    found: list[str] = []
    for pattern, label in patterns:
        if re.search(pattern, compact, re.IGNORECASE) and label not in found:
            found.append(label)
    return found


def _extract_structured_observations(texts: tuple[str, ...]) -> dict[str, list[str]]:
    haystack = "\n".join(text for text in texts if text)
    specs = {
        "role_title": [
            r"(?:我的职位是|职位是|我是|我担任|我负责|role is|title is)\s*[:：]?\s*([^，。,.!?！？；;\n]{2,40})",
        ],
        "industry": [
            r"(?:所属行业是|行业是|我们行业是|industry is)\s*[:：]?\s*([^，。,.!?！？；;\n]{2,40})",
        ],
        "company_brand": [
            r"(?:公司(?:/品牌)?是|公司叫|品牌是|品牌叫|company is|brand is)\s*[:：]?\s*([^，。,.!?！？；;\n]{2,50})",
        ],
        "products": [
            r"(?:主要产品是|产品是|主营产品是|我们卖|我们做|product is|products are)\s*[:：]?\s*([^，。,.!?！？；;\n]{2,60})",
        ],
        "target_customers": [
            r"(?:目标客户是|目标用户是|目标受众是|受众是|人群是|target customers are|audience is)\s*[:：]?\s*([^，。,.!?！？；;\n]{2,80})",
        ],
        "channels": [
            r"(?:常用渠道是|主要渠道是|渠道是|发布在|投放在|平台是|channel is|channels are)\s*[:：]?\s*([^，。,.!?！？；;\n]{2,60})",
        ],
        "tone_preferences": [
            r"(?:语气偏好是|内容语气是|语气是|风格是|调性是|tone is|voice is)\s*[:：]?\s*([^，。,.!?！？；;\n]{2,60})",
        ],
        "report_format_preferences": [
            r"(?:报告格式偏好是|报告格式是|输出格式是|交付格式是|format is|report format is)\s*[:：]?\s*([^，。,.!?！？；;\n]{2,80})",
        ],
        "kpi_data_preferences": [
            r"(?:KPI(?:/数据口径)?偏好是|数据口径是|指标口径是|KPI是|metric definition is|kpi is)\s*[:：]?\s*([^，。,.!?！？；;\n]{2,80})",
        ],
        "other_preferences": [
            r"(?:长期偏好是|其他偏好是|偏好是|我习惯|我希望以后|prefer)\s*[:：]?\s*([^，。,.!?！？；;\n]{2,100})",
        ],
    }
    out: dict[str, list[str]] = {}
    for field, patterns in specs.items():
        values: list[str] = []
        for pattern in patterns:
            for match in re.finditer(pattern, haystack, re.IGNORECASE):
                value = _clean_observation_value(match.group(1))
                if value and value not in values:
                    values.append(value)
        if values:
            out[field] = values[:6]
    return out


def _clean_observation_value(value: str) -> str:
    cleaned = re.sub(r"\s+", " ", value).strip(" ：:，,。.;；")
    cleaned = re.sub(r"^(需要|希望|偏好|使用|采用)", "", cleaned).strip(" ：:，,。.;；")
    return _clip(cleaned, 80) if len(cleaned) >= 2 else ""


_INDUSTRY_PATTERNS = [
    (r"服装|女装|男装|穿搭|fashion|apparel", "Fashion/apparel"),
    (r"saas|软件|系统|平台|crm|企业服务", "B2B SaaS / enterprise services"),
    (r"教育|课程|培训", "Education/training"),
    (r"消费品|零售|电商|店铺", "Consumer goods / ecommerce"),
]

_PRODUCT_PATTERNS = [
    (r"服装|衣服|款式|女装|男装|裙|裤|外套", "Apparel products"),
    (r"saas|软件|系统|平台|工具|解决方案", "Software / SaaS product"),
    (r"课程|培训|资料|社群", "Education product"),
]

_AUDIENCE_PATTERNS = [
    (r"b2b|企业客户|决策者|老板|创始人|管理层", "B2B decision makers"),
    (r"市场|运营|增长|销售|bd", "Marketing / growth / sales teams"),
    (r"女性|女生|白领|通勤|宝妈|学生", "Consumer lifestyle audiences"),
]

_CHANNEL_PATTERNS = [
    (r"小红书|xhs", "Little Red Book"),
    (r"linkedin|领英", "LinkedIn"),
    (r"公众号|微信|朋友圈|社群|私域", "WeChat / owned channels"),
    (r"抖音|短视频|视频号|tiktok", "Short video"),
    (r"邮件|email|newsletter", "Email/newsletter"),
]

_TONE_PATTERNS = [
    (r"专业|正式|克制|权威", "Professional"),
    (r"亲切|自然|种草|真实", "Authentic and friendly"),
    (r"高级|精致|质感", "Premium/refined"),
    (r"幽默|活泼|年轻", "Playful/young"),
]

_DELIVERABLE_PATTERNS = [
    (r"文案|post|copy|caption", "Marketing copy"),
    (r"报告|pdf|brief", "Report/brief"),
    (r"方案|campaign|计划|策划", "Campaign plan"),
    (r"邮件|email", "Email"),
    (r"脚本|短视频|口播", "Video script"),
]

_ROLE_PATTERNS = [
    (r"marketingdirector|cmo|founder|ceo", "Marketing or business owner"),
    (r"市场|营销|增长|运营", "Marketing / growth / operations"),
    (r"销售|bd|商务", "Sales / business development"),
]

_COMPANY_PATTERNS = [
    (r"我们公司|我司|品牌|company|brand", "Company/brand context discussed"),
]

_KPI_PATTERNS = [
    (r"kpi|roi|ctr|cpa|cac|gmv", "Performance and conversion metrics"),
    (r"转化率|线索|留资|销售额|获客成本", "Performance and conversion metrics"),
    (r"曝光|阅读|互动|点赞|收藏|评论|分享", "Reach and engagement metrics"),
]
