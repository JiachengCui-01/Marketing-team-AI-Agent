"""LLM-driven clarification planner.

Given a user's task request (and their long-term marketing profile), a cheap
fast model decides whether asking 1-3 short questions would materially improve
the deliverable, and if so generates those questions with concrete quick-reply
options — in the user's language, skipping anything already known.

Degrades gracefully: when disabled, unconfigured, or on any error it returns
``needs_clarification=False`` with a ``source`` marker so the frontend can fall
back to its heuristic clarification flow.
"""
from __future__ import annotations

import logging
from typing import Any

from marketing_agent import config

from . import llm, memory

logger = logging.getLogger(__name__)

_TOOL_NAME = "plan_clarification"
_MAX_QUESTIONS = 3
_MAX_OPTIONS = 4

_SYSTEM = (
    "You help a marketing AI decide whether to ask the user a few clarifying questions "
    "before starting a task. You are given the user's request and their known long-term "
    "marketing profile.\n"
    "Decide if asking 1-3 SHORT questions would materially improve the deliverable. "
    "If the request is already clear enough, or the missing details are already in the "
    "profile, set needs_clarification=false and ask nothing — do not nitpick.\n"
    "When you do ask: make each question specific to THIS request, phrased in the user's "
    "language; give 2-4 concrete quick-reply options plus allow_custom=true so the user can "
    "type their own answer. Never ask about something already stated in the request or the "
    "profile. Prefer the single most decision-changing question; ask more only when each is "
    "clearly worth the user's time."
)


def plan_clarification(user_id: str, prompt: str, locale: str = "zh") -> dict:
    prompt = (prompt or "").strip()
    if not prompt:
        return _empty("empty")
    if not config.clarify_llm_enabled():
        return _empty("disabled")

    client = llm.get_client()
    if client is None:
        return _empty("unavailable")

    try:
        profile = memory.merged_profile(user_id)
        response = client.messages.create(
            model=config.CLARIFY_MODEL,
            max_tokens=700,
            system=_SYSTEM,
            tools=[_TOOL],
            tool_choice={"type": "tool", "name": _TOOL_NAME},
            messages=[{"role": "user", "content": _user_content(prompt, profile, locale)}],
        )
        plan = _parse(response)
        plan["source"] = "llm"
        return plan
    except Exception:  # noqa: BLE001 — clarification must never block a turn
        logger.exception("clarification planning failed; frontend will fall back")
        return _empty("error")


def _empty(source: str) -> dict:
    return {"needs_clarification": False, "questions": [], "source": source}


def _user_content(prompt: str, profile: dict, locale: str) -> str:
    lang = "Chinese" if locale == "zh" else "English"
    if profile:
        known = "\n".join(
            f"- {memory.MARKETING_PROFILE_FIELDS.get(field, field)}: {', '.join(values)}"
            for field, values in profile.items()
            if values
        )
    else:
        known = "(none)"
    return (
        f"User request:\n{prompt[:4000]}\n\n"
        f"Known long-term marketing profile (do not re-ask these):\n{known}\n\n"
        f"Write any questions and options in {lang}."
    )


def _parse(response: Any) -> dict:
    for block in getattr(response, "content", []) or []:
        if getattr(block, "type", None) != "tool_use" or getattr(block, "name", None) != _TOOL_NAME:
            continue
        data = block.input if isinstance(block.input, dict) else {}
        questions = _normalize_questions(data.get("questions"))
        needs = bool(data.get("needs_clarification")) and bool(questions)
        return {"needs_clarification": needs, "questions": questions if needs else []}
    return {"needs_clarification": False, "questions": []}


def _normalize_questions(raw: Any) -> list[dict]:
    if not isinstance(raw, list):
        return []
    out: list[dict] = []
    for idx, item in enumerate(raw):
        if not isinstance(item, dict):
            continue
        question = str(item.get("question") or "").strip()
        if not question:
            continue
        options: list[dict] = []
        for opt in item.get("options") or []:
            if not isinstance(opt, dict):
                continue
            label = str(opt.get("label") or "").strip()
            if not label:
                continue
            value = str(opt.get("value") or label).strip()
            options.append({"label": label[:80], "value": value[:200]})
            if len(options) >= _MAX_OPTIONS:
                break
        out.append({
            "id": str(item.get("id") or f"q{idx + 1}").strip() or f"q{idx + 1}",
            "question": question[:300],
            "options": options,
            "allow_custom": bool(item.get("allow_custom", True)),
        })
        if len(out) >= _MAX_QUESTIONS:
            break
    return out


_TOOL = {
    "name": _TOOL_NAME,
    "description": "Decide whether to ask clarifying questions and, if so, provide them.",
    "input_schema": {
        "type": "object",
        "properties": {
            "needs_clarification": {
                "type": "boolean",
                "description": "True only if asking would materially improve the result.",
            },
            "questions": {
                "type": "array",
                "description": "1-3 short, request-specific questions (empty if not needed).",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "question": {"type": "string", "description": "In the user's language."},
                        "options": {
                            "type": "array",
                            "description": "2-4 concrete quick-reply options.",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "label": {"type": "string", "description": "Short chip label."},
                                    "value": {"type": "string", "description": "The answer text to apply."},
                                },
                                "required": ["label"],
                            },
                        },
                        "allow_custom": {"type": "boolean"},
                    },
                    "required": ["question", "options"],
                },
            },
        },
        "required": ["needs_clarification", "questions"],
    },
}
