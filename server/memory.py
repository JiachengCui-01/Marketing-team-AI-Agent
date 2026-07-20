"""Conversation memory management for marketing-agent sessions.

The database keeps the full transcript. This module builds a compact working
context for model calls: long-term marketing profile, compressed older turns,
and a recent sliding window under a rough token budget.
"""
from __future__ import annotations

import json
import re
from typing import Any

from marketing_agent.conversation import Conversation

from . import db

RECENT_MESSAGE_WINDOW = 12
CONTEXT_TOKEN_BUDGET = 24000
SUMMARY_CHAR_BUDGET = 3200
RECENT_MESSAGE_CHAR_CAP = 5000

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

LEGACY_PROFILE_FIELDS = {
    "industries": "Industries",
    "audiences": "Audiences",
    "tones": "Tone/style",
    "deliverables": "Common deliverables",
}


def build_conversation(session_id: str, user_id: str) -> Conversation | None:
    if db.get_session(session_id, user_id) is None:
        return None
    rows = db.list_messages(session_id)
    summary = _summary_for_rows(session_id, user_id, rows)
    recent_rows = rows[-RECENT_MESSAGE_WINDOW:]

    messages: list[dict[str, Any]] = []
    memory_blocks: list[str] = []
    profile = db.get_user_marketing_memory(user_id)
    profile_text = _format_profile(profile.get("profile", {}) if profile else {})
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
    current = (db.get_user_marketing_memory(user_id) or {}).get("profile") or {}
    profile = {
        "role_title": _merge_list(current.get("role_title"), _extract_values(texts, _ROLE_PATTERNS)),
        "industry": _merge_list(
            current.get("industry") or current.get("industries"),
            _extract_values(texts, _INDUSTRY_PATTERNS),
        ),
        "company_brand": _merge_list(current.get("company_brand"), _extract_values(texts, _COMPANY_PATTERNS)),
        "products": _merge_list(current.get("products"), _extract_values(texts, _PRODUCT_PATTERNS)),
        "target_customers": _merge_list(
            current.get("target_customers") or current.get("audiences"),
            _extract_values(texts, _AUDIENCE_PATTERNS),
        ),
        "channels": _merge_list(current.get("channels"), _extract_values(texts, _CHANNEL_PATTERNS)),
        "tone_preferences": _merge_list(
            current.get("tone_preferences") or current.get("tones"),
            _extract_values(texts, _TONE_PATTERNS),
        ),
        "report_format_preferences": _merge_list(
            current.get("report_format_preferences") or current.get("deliverables"),
            _extract_values(texts, _DELIVERABLE_PATTERNS),
        ),
        "kpi_data_preferences": _merge_list(current.get("kpi_data_preferences"), _extract_values(texts, _KPI_PATTERNS)),
        "other_preferences": _merge_list(current.get("other_preferences"), []),
    }
    profile = {key: value for key, value in profile.items() if value}
    if not profile:
        return None
    return db.upsert_user_marketing_memory(user_id, profile)


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
    if not profile:
        return ""
    lines = []
    for key, label in MARKETING_PROFILE_FIELDS.items():
        values = profile.get(key)
        if values:
            lines.append(f"- {label}: {', '.join(_as_list(values)[:8])}")
    for key, label in LEGACY_PROFILE_FIELDS.items():
        values = profile.get(key)
        if values:
            lines.append(f"- {label}: {', '.join(_as_list(values)[:8])}")
    if not lines:
        return ""
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
    for value in [*_as_list(existing), *discovered]:
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
