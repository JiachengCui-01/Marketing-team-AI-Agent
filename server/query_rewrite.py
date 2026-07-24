"""Query understanding for knowledge-base retrieval.

A cheap fast model rewrites the raw user query into a self-contained search query by:
  - coreference resolution (指代消解): resolve "它/那个/上面说的" against recent turns,
  - synonym / related-term expansion (同义扩展): e.g. 交通费↔差旅费, 年假↔带薪休假,
  - intent recognition (意图识别): policy_lookup / how_to / factual / definition / other.

Degrades gracefully: when disabled, unconfigured, or on any error it returns the raw
query with no expansions and intent="unknown" so retrieval still runs.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

from marketing_agent import config

from . import llm

logger = logging.getLogger(__name__)

_FALSEY = {"0", "false", "no", "off", ""}
_TOOL_NAME = "rewrite_query"
_INTENTS = ["policy_lookup", "how_to", "factual", "definition", "other"]

_SYSTEM = (
    "你是企业知识库检索的查询理解模块。给定用户的原始问题和最近的对话，输出一个用于检索的改写结果：\n"
    "1) resolved_query：把指代（它/这个/上面提到的/他）用对话上下文补全，改写成不依赖上下文、可独立检索的完整问题。\n"
    "2) expansions：3-8 个同义词或相关关键词（含中英文近义，如 交通费/差旅费、报销/费用报销、年假/带薪休假），用于提高召回。\n"
    "3) intent：从 policy_lookup(制度/规定查询), how_to(操作步骤), factual(具体事实), definition(概念解释), other 中选一个。\n"
    "只输出与本次问题相关的词，不要编造无关词。使用与用户相同的语言。"
)

_TOOL = {
    "name": _TOOL_NAME,
    "description": "Return the rewritten retrieval query, expansion terms, and detected intent.",
    "input_schema": {
        "type": "object",
        "properties": {
            "resolved_query": {"type": "string"},
            "expansions": {"type": "array", "items": {"type": "string"}},
            "intent": {"type": "string", "enum": _INTENTS},
        },
        "required": ["resolved_query", "expansions", "intent"],
    },
}


def enabled() -> bool:
    return os.environ.get("MARKETING_AGENT_KB_QUERY_REWRITE", "1").strip().lower() not in _FALSEY


def _fallback(query: str, source: str) -> dict:
    return {"resolved": query, "expansions": [], "intent": "unknown", "source": source}


def rewrite_query(query: str, history: list[dict] | None = None, locale: str = "zh") -> dict:
    """Return ``{resolved, expansions, intent, source}``."""
    query = (query or "").strip()
    if not query:
        return _fallback(query, "empty")
    if not enabled():
        return _fallback(query, "disabled")
    client = llm.get_client()
    if client is None:
        return _fallback(query, "unavailable")
    try:
        response = client.messages.create(
            model=config.CLARIFY_MODEL,
            max_tokens=500,
            system=_SYSTEM,
            tools=[_TOOL],
            tool_choice={"type": "tool", "name": _TOOL_NAME},
            messages=[{"role": "user", "content": _user_content(query, history, locale)}],
        )
        return _parse(response, query)
    except Exception:  # noqa: BLE001 — retrieval must never break on rewrite
        logger.exception("query rewrite failed; using raw query")
        return _fallback(query, "error")


def _user_content(query: str, history: list[dict] | None, locale: str) -> str:
    parts = []
    if history:
        lines = []
        for turn in history[-6:]:
            role = "用户" if turn.get("role") == "user" else "助手"
            text = str(turn.get("text") or "").strip()
            if text:
                lines.append(f"{role}：{text[:300]}")
        if lines:
            parts.append("最近对话：\n" + "\n".join(lines))
    parts.append(f"原始问题：{query}")
    parts.append(f"语言：{locale}")
    return "\n\n".join(parts)


def _parse(response: Any, query: str) -> dict:
    for block in getattr(response, "content", []) or []:
        if getattr(block, "type", None) == "tool_use" and block.name == _TOOL_NAME:
            data = block.input or {}
            resolved = str(data.get("resolved_query") or query).strip() or query
            expansions = [str(x).strip() for x in (data.get("expansions") or []) if str(x).strip()]
            intent = str(data.get("intent") or "other")
            if intent not in _INTENTS:
                intent = "other"
            return {
                "resolved": resolved,
                "expansions": expansions[:8],
                "intent": intent,
                "source": "llm",
            }
    return _fallback(query, "no_tool_call")
