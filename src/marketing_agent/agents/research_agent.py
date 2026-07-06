"""Market & competitor research agent — server-side web search with citations."""
from __future__ import annotations

from typing import Any

import anthropic

from ..config import MODEL_ID, SUBAGENT_EFFORT
from .base import unavailable_markdown

SYSTEM = """You are a marketing research analyst. You investigate market trends, competitor
moves, and industry signals using the web_search tool.

Rules:

- Start with one compact web search query that covers the user's task.
- Gather 3-5 distinct, reputable sources when available.
- You may run up to two focused follow-up searches if the first result set is
  malformed, empty, or lacks enough date-confirmed sources.
- If the server reports a search/tool limit after you have any relevant sources,
  stop searching and synthesize from the sources already gathered.
- Cite every claim with a URL and (where visible) publication date.
- Distinguish observed facts from inferences — label inferences as such.
- Prefer recent material (≤ 6 months) for "what's happening" questions; older sources are fine
  for background/context.
- If sources disagree, surface the disagreement.

Output format (markdown):

## Summary
2-4 sentences capturing the most important findings.

## Findings
- Fact / trend / competitor move — [source title, date](url)
- ...

## Implications for Marketing
2-3 bullets on what this means for our team's positioning, messaging, or roadmap.

## Sources
Numbered list of all URLs used.
"""

# The basic search tool is more predictable for time-windowed news retrieval than
# dynamic filtering, and three searches is Anthropic's recommended low-latency cap.
TOOLS = [{"type": "web_search_20250305", "name": "web_search", "max_uses": 3}]


def _research_unavailable(exc: Exception) -> str:
    return unavailable_markdown(
        exc,
        title="## Research Unavailable",
        feature="web research",
        retry_noun="research request",
        credits_for="web search",
    )


def run(
    client: anthropic.Anthropic,
    task: str,
    topics: list[str],
    competitors: list[str] | None = None,
) -> str:
    parts = [
        f"Task: {task}",
        f"Topics: {', '.join(topics)}",
    ]
    if competitors:
        parts.append(f"Competitors of interest: {', '.join(competitors)}")

    try:
        response = client.messages.create(
            model=MODEL_ID,
            max_tokens=4096,
            system=SYSTEM,
            thinking={"type": "adaptive"},
            output_config={"effort": SUBAGENT_EFFORT},
            tools=TOOLS,
            messages=[{"role": "user", "content": "\n".join(parts)}],
        )
        text = _extract_text(response.content)
        if text:
            return text
        return (
            "## Research Unavailable\n\n"
            f"The research call ended with stop_reason={response.stop_reason!r} "
            "but returned no text."
        )
    except anthropic.APIError as exc:
        return _research_unavailable(exc)


def _extract_text(content: list[Any]) -> str:
    return "\n".join(block.text for block in content if block.type == "text").strip()
