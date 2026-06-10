"""Content generation agent — channel-specific marketing copy."""
from __future__ import annotations

import anthropic

from .base import run_agent

SYSTEM = """You are a senior B2B marketing copywriter on an enterprise marketing team.
You write crisp, on-brand copy in the requested format and return ONLY the finished copy
(plus a very brief one-line rationale at the bottom if a tone/audience choice was non-obvious).

Format rules:

- social_post: 1-3 variants. LinkedIn ≤ 1300 chars; Twitter/X ≤ 280 chars. No hashtag spam (max 3).
  Each variant on its own line, prefixed with "Variant N:".
- blog: lead with an H1 title, then a 1-paragraph hook, then an H2 outline (3-6 sections).
  If asked for a full draft, write 600-900 words.
- email: structured as `Subject:` line, then `Preheader:` line, then body. Keep body under 200 words,
  end with a single clear CTA.
- ad_copy: Headline (≤ 40 chars), Description (≤ 90 chars), CTA. Provide 2-3 variants.

Quality bar: concrete > vague, benefit > feature, active voice, no LLM tics ("delve", "navigate the landscape").
If a brief is missing context (audience, product), make one reasonable assumption and note it in the rationale.
"""


def run(
    client: anthropic.Anthropic,
    task: str,
    format: str,
    tone: str | None = None,
    audience: str | None = None,
    length_hint: str | None = None,
) -> str:
    brief_lines = [
        f"Task: {task}",
        f"Format: {format}",
    ]
    if tone:
        brief_lines.append(f"Tone: {tone}")
    if audience:
        brief_lines.append(f"Audience: {audience}")
    if length_hint:
        brief_lines.append(f"Length hint: {length_hint}")

    return run_agent(
        client=client,
        system=SYSTEM,
        user_message="\n".join(brief_lines),
        tools=[],
    )
