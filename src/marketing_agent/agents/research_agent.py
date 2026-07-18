"""Market & competitor research agent — server-side web search with citations."""
from __future__ import annotations

from typing import Any

import anthropic

from marketing_agent.source_scoring import annotate_markdown_with_source_tiers

from ..config import MODEL_ID, SUBAGENT_EFFORT
from .base import unavailable_markdown

SYSTEM = """You are a marketing research analyst. You investigate market trends, competitor
moves, and industry signals using the web_search tool.

Rules:

- Start with one compact web search query that covers the user's task.
- Gather 3-5 distinct, reputable sources when available.
- Prioritize Tier 1 and Tier 2 sources:
  * Tier 1: official/regulatory/primary authority sources.
  * Tier 2: authoritative media, research institutions, and official company websites.
  * Tier 3: industry self-media or personal commentary.
  * Tier 4: community discussions and social platforms.
- Use Tier 3/Tier 4 only as weak market-signal context. They must not be the sole
  basis for factual claims, and you must naturally state the uncertainty they add.
- You may run up to two focused follow-up searches if the first result set is
  malformed, empty, or lacks enough date-confirmed sources.
- If the server reports a search/tool limit after you have any relevant sources,
  stop searching and synthesize from the sources already gathered.
- Cite every claim with a URL and (where visible) publication date.
- For each key fact, trend, or competitor move in the body, keep 1-3 citation
  links at the end of that sentence or bullet, similar to academic inline
  references. Do not move citations into a standalone Sources section.
- Distinguish observed facts from inferences — label inferences as such.
- Prefer recent material (≤ 6 months) for "what's happening" questions; older sources are fine
  for background/context.
- If sources disagree, surface the disagreement.
- Do not add a final raw URL list. The system will extract inline citation URLs,
  score source tiers, and append the Source Credibility section.
- Include a natural source-risk note whenever Tier 3/Tier 4 sources appear:
  they are weak market-signal context and cannot independently support factual
  claims.

Output format (markdown):

## Summary
2-4 sentences capturing the most important findings.

## Findings
- Fact / trend / competitor move — concise explanation ending with 1-3 links
  like [source title, date](url)
- ...

## Implications for Marketing
2-3 bullets on what this means for our team's positioning, messaging, or roadmap.

## Source Notes
Only include this section when needed to explain source disagreement, missing
strong sources, or Tier 3/Tier 4 uncertainty. Do not list raw URLs here.
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
    response_language: str | None = None,
) -> str:
    parts = [
        f"Task: {task}",
        f"Topics: {', '.join(topics)}",
    ]
    if competitors:
        parts.append(f"Competitors of interest: {', '.join(competitors)}")

    system = SYSTEM
    if response_language == "zh":
        system += (
            "\n\nLANGUAGE REQUIREMENT: Write every part of the final response in "
            "Simplified Chinese, including any introductory sentence and all headings. "
            "Do not narrate the search process in English."
        )
    elif response_language == "en":
        system += (
            "\n\nLANGUAGE REQUIREMENT: Write every part of the final response in English, "
            "including any introductory sentence and all headings."
        )

    try:
        response = client.messages.create(
            model=MODEL_ID,
            max_tokens=4096,
            system=system,
            thinking={"type": "adaptive"},
            output_config={"effort": SUBAGENT_EFFORT},
            tools=TOOLS,
            messages=[{"role": "user", "content": "\n".join(parts)}],
        )
        text = _extract_text(response.content)
        if text:
            return annotate_markdown_with_source_tiers(text, language=response_language)
        return (
            "## Research Unavailable\n\n"
            f"The research call ended with stop_reason={response.stop_reason!r} "
            "but returned no text."
        )
    except anthropic.APIError as exc:
        return _research_unavailable(exc)


def _extract_text(content: list[Any]) -> str:
    parts: list[str] = []
    for block in content:
        if block.type != "text":
            continue
        text = block.text
        citations = _block_citation_links(block)
        if citations and not any(url in text for _, url in citations):
            text = text.rstrip() + " " + " ".join(f"[{title}]({url})" for title, url in citations)
        parts.append(text)
    return "\n".join(parts).strip()


def _block_citation_links(block: Any) -> list[tuple[str, str]]:
    links: list[tuple[str, str]] = []
    seen: set[str] = set()
    for citation in getattr(block, "citations", None) or []:
        url = str(getattr(citation, "url", "") or "").strip()
        if not url or url in seen:
            continue
        title = str(getattr(citation, "title", "") or "").strip() or url
        seen.add(url)
        links.append((title, url))
    return links
