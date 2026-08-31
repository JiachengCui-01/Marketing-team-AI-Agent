"""Extraction of long-term marketing profile observations from prompt text.

Enterprise prompts span every industry and language, so a fixed keyword table
cannot generalize. This module uses a cheap, fast LLM to pull durable profile
facts in the user's own words, and degrades gracefully to the deterministic
heuristic in ``memory`` when no client is available or the call fails — so the
feature never breaks offline or in tests.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Sequence

from marketing_agent import config

from . import llm

logger = logging.getLogger(__name__)

_TOOL_NAME = "record_marketing_profile"

_SYSTEM = (
    "You extract durable business profile facts from a user's message for the long-term "
    "memory of a marketing workspace. The company designs large furniture, has it built by "
    "contract suppliers, and sells it direct to consumers in the United States.\n"
    "Only record facts that are stated or strongly implied and that stay true across future "
    "requests (role, category/industry, company/brand, product line, target customers, "
    "sales and marketing channels, tone, deliverable format, KPI/metric definitions, other "
    "standing preferences). Record each value in the user's own words and original language; "
    "do not translate or invent. Leave a field empty when unknown — never guess.\n"
    "Do NOT record a one-off product spec (a specific sofa's seat depth, one SKU's carton "
    "count) as a profile fact — those belong to a single task, not to the standing profile. "
    "Do record durable ones, such as the fact that the line is all solid wood, or that "
    "everything ships LTL.\n"
    "Set explicit=true only for direct self-declarations (e.g. 'our main line is solid oak "
    "dining tables', 'we sell mostly on Amazon and Wayfair', '我的职位是海外市场负责人'); "
    "set explicit=false for incidental mentions inferred from a one-off task.\n"
    "You may be given already-known values for this user. When an extracted fact refers to the "
    "same thing as a known value for that field — even if paraphrased, abbreviated, or a longer/"
    "shorter form (e.g. '实木餐桌系列' vs '实木餐桌') — output that known value VERBATIM so "
    "the counts merge. Only output a new value when it is genuinely a different thing."
)


@dataclass(frozen=True)
class Observation:
    field: str
    value: str
    explicit: bool


def extract_observations(
    texts: Sequence[str], *, use_llm: bool, known_values: dict[str, list[str]] | None = None
) -> list[Observation]:
    """Return profile observations for the given text(s).

    Tries the LLM extractor first when enabled and a client is configured;
    otherwise (or on any failure) falls back to the deterministic heuristic.
    ``known_values`` (existing evidence values per field) lets the LLM reuse a
    canonical form so paraphrases of the same thing merge instead of fragmenting.
    """
    joined = "\n\n".join(text for text in texts if text).strip()
    if not joined:
        return []

    if use_llm:
        client = llm.get_client()
        if client is not None:
            try:
                observations = _llm_observations(client, joined, known_values or {})
                if observations:
                    return observations
            except Exception:  # noqa: BLE001 — never let learning break a turn
                logger.exception("LLM memory extraction failed; using heuristic fallback")

    return _heuristic_observations(tuple(texts))


def _heuristic_observations(texts: tuple[str, ...]) -> list[Observation]:
    from . import memory  # local import avoids an import cycle

    return [Observation(field, value, explicit) for field, value, explicit in memory.heuristic_observations(texts)]


def _llm_observations(client, joined: str, known_values: dict[str, list[str]]) -> list[Observation]:
    from . import memory  # local import avoids an import cycle

    response = client.messages.create(
        model=config.MEMORY_EXTRACTION_MODEL,
        max_tokens=1024,
        system=_SYSTEM,
        tools=[_build_tool(memory.MARKETING_PROFILE_FIELDS)],
        tool_choice={"type": "tool", "name": _TOOL_NAME},
        messages=[{"role": "user", "content": _content(joined, known_values, memory.MARKETING_PROFILE_FIELDS)}],
    )

    observations: list[Observation] = []
    for block in response.content:
        if getattr(block, "type", None) != "tool_use" or getattr(block, "name", None) != _TOOL_NAME:
            continue
        data = block.input if isinstance(block.input, dict) else {}
        for field, items in data.items():
            if field not in memory.MARKETING_PROFILE_FIELDS or not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                value = memory._clip(str(item.get("value") or ""), 120)
                if not value:
                    continue
                observations.append(Observation(field, value, bool(item.get("explicit"))))
    return observations


def _content(joined: str, known_values: dict[str, list[str]], fields: dict[str, str]) -> str:
    lines = []
    for field, label in fields.items():
        vals = (known_values or {}).get(field)
        if vals:
            lines.append(f"- {label} ({field}): {', '.join(vals)}")
    known_block = "\n".join(lines) if lines else "(none)"
    return (
        f"User message:\n{joined[:6000]}\n\n"
        f"Already-known values for this user (reuse the exact string when a fact refers to the "
        f"same thing, even if worded differently):\n{known_block}"
    )


def _build_tool(fields: dict[str, str]) -> dict:
    return {
        "name": _TOOL_NAME,
        "description": "Record durable business profile facts stated by the user.",
        "input_schema": {
            "type": "object",
            "properties": {
                field: {
                    "type": "array",
                    "description": label,
                    "items": {
                        "type": "object",
                        "properties": {
                            "value": {"type": "string", "description": "The fact in the user's own words."},
                            "explicit": {"type": "boolean", "description": "True only for a direct self-declaration."},
                        },
                        "required": ["value", "explicit"],
                    },
                }
                for field, label in fields.items()
            },
        },
    }
