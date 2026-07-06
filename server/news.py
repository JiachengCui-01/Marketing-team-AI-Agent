"""Daily industry-news summarization.

Reuses the research agent (server-side web search with citations) to summarize the
most recent 24 hours of industry news for a user's configured topic. Used both by
the manual "refresh now" endpoint and by the background scheduler in ``main.py``.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import anthropic

from marketing_agent.agents import research_agent

from . import db

WINDOW_HOURS = 24


def _detail_instruction(detail_level: str) -> str:
    if detail_level == "detailed":
        return (
            "Provide a detailed digest: group items by theme, and for each item give 2-3 "
            "sentences of context and why it matters."
        )
    return "Keep it brief: one concise sentence per item, only the most important developments."


def build_task(industry: str, detail_level: str, tz_now: datetime) -> tuple[str, float, float]:
    """Return (task_prompt, window_start_ts, window_end_ts)."""
    window_end = tz_now
    window_start = tz_now - timedelta(hours=WINDOW_HOURS)
    fmt = "%Y-%m-%d %H:%M %Z"
    task = (
        f"Summarize the most important {industry} industry news published in the last "
        f"{WINDOW_HOURS} hours — strictly between {window_start.strftime(fmt)} and "
        f"{window_end.strftime(fmt)}. Only include items published within that window; "
        f"ignore older material. {_detail_instruction(detail_level)} "
        f"If little or nothing was published in this window, say so plainly rather than "
        f"padding with older news."
    )
    return task, window_start.timestamp(), window_end.timestamp()


def generate_summary(config: dict, client: anthropic.Anthropic | None = None) -> dict:
    """Generate and persist a news summary for the given news config row.

    Returns the persisted summary record.
    """
    client = client or anthropic.Anthropic()
    industry = config["industry"]
    try:
        tz = ZoneInfo(config.get("timezone") or "UTC")
    except Exception:  # noqa: BLE001 - unknown tz string
        tz = ZoneInfo("UTC")
    now = datetime.now(tz)

    task, window_start, window_end = build_task(industry, config["detail_level"], now)
    summary = research_agent.run(client, task=task, topics=[industry])

    record = db.add_news_summary(
        user_id=config["user_id"],
        config_id=config.get("id"),
        summary=summary,
        generated_at=time.time(),
        window_start=window_start,
        window_end=window_end,
    )
    db.set_news_config_last_run(config["user_id"], record["generated_at"])
    return record
