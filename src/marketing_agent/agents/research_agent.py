"""Market & competitor research agent — web search with citations.

Search is a client-side tool (``tools/web_search.py``) because DeepSeek has no
server-side search. The model still writes source URLs inline, so downstream
source-tier scoring is unchanged.
"""
from __future__ import annotations

from marketing_agent.source_scoring import annotate_markdown_with_source_tiers

from .. import llm_client
from ..config import SUBAGENT_EFFORT, SUBAGENT_MAX_TOKENS
from ..domain import BRAND
from ..tools import web_search
from .base import run_agent, unavailable_markdown

SYSTEM = f"""You are the market research analyst for {BRAND}, a design-led
large-furniture brand selling direct to consumers in the United States. You investigate
US furniture and home-furnishings demand, competing brands and marketplace listings,
category and style trends, marketplace policy changes, tariffs and duties, and
product-safety rules — using the web_search tool.

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
  malformed, empty, or lacks enough date-confirmed sources. Never run more than
  three searches in total.
- If a search returns an error or no usable results, stop searching and synthesize
  from whatever sources you already have.
- Only cite URLs that appeared in a web_search result. Never invent a URL, a
  headline, or a publication date.
- Cite every claim with a URL and (where visible) publication date.
- For each key fact, trend, or competitor move in the body, keep 1-3 citation
  links at the end of that sentence or bullet, similar to academic inline
  references. Do not move citations into a standalone Sources section.
- Distinguish observed facts from inferences — label inferences as such.
- Prefer recent material (≤ 6 months) for "what's happening" questions; older sources are fine
  for background/context.
- For this business, weight these source types highly when relevant: US furniture trade
  press (Furniture Today, Home News Now, HFN, Business of Home), retail and housing
  demand data, and primary regulators for duties and safety (USITC, CBP, CPSC,
  trade.gov). A tariff or CPSC rule change is a material finding, not background.
- When comparing competitors, cite the actual listing or brand page you read. Do not
  state a competitor's price, dimension, or material from memory.
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

## Implications for Us
2-3 bullets on what this means for assortment and product selection, pricing and
positioning, listing and content angles, or import/compliance risk.

## Source Notes
Only include this section when needed to explain source disagreement, missing
strong sources, or Tier 3/Tier 4 uncertainty. Do not list raw URLs here.
"""

TOOLS = [web_search.WEB_SEARCH_TOOL]

# Three searches is a reasonable low-latency cap; the loop needs a couple of extra
# rounds on top for the synthesis turn.
MAX_SEARCH_ROUNDS = 6


def _research_unavailable(exc: Exception) -> str:
    return unavailable_markdown(
        exc,
        title="## Research Unavailable",
        feature="web research",
        retry_noun="research request",
        credits_for="web research",
    )


def _search_unconfigured() -> str:
    return "\n".join(
        [
            "## Research Unavailable",
            "",
            web_search.unavailable_reason(),
            "",
            "## What to do next",
            "1. Obtain a key from one of the supported search providers "
            "(Tavily, Serper, Brave, or 博查 Bocha).",
            "2. Set the matching environment variable on the API server and restart it.",
            "3. Retry the research request.",
        ]
    )


def run(
    client: llm_client.DeepSeek,
    task: str,
    topics: list[str],
    competitors: list[str] | None = None,
    response_language: str | None = None,
) -> str:
    if not web_search.is_available():
        return _search_unconfigured()

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
        text = run_agent(
            client=client,
            system=system,
            user_message="\n".join(parts),
            tools=TOOLS,
            client_tool_handlers={"web_search": web_search.handle_web_search},
            effort=SUBAGENT_EFFORT,
            max_tokens=SUBAGENT_MAX_TOKENS,
        ).strip()
    except llm_client.APIError as exc:
        return _research_unavailable(exc)

    if text:
        return annotate_markdown_with_source_tiers(text, language=response_language)
    return (
        "## Research Unavailable\n\n"
        "The research call returned no text. Retry the research request."
    )
