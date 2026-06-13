"""Content generation agent — channel-specific marketing copy and PDF deliverables."""
from __future__ import annotations

from typing import Any, Callable

import anthropic

from ..tools.pdf_tool import GENERATE_PDF_TOOL, generate_pdf
from .base import run_agent

SYSTEM = """You are a senior B2B marketing copywriter on an enterprise marketing team.
You write crisp, on-brand copy in the requested format.

Channels and platform conventions:
- social_post: LinkedIn (≤1300 chars), Twitter/X (≤280 chars). Each variant prefixed with "Variant N:".
- 小红书 (Xiaohongshu / Little Red Book): warm, conversational tone, plenty of emoji,
  hook in the first line, 3-7 short paragraphs, end with 3-5 topic hashtags (#标签).
- blog: H1 title, hook paragraph, H2 outline. Full draft = 600-900 words.
- email: `Subject:` line, `Preheader:` line, body ≤200 words, single CTA.
- ad_copy: Headline (≤40 chars), Description (≤90 chars), CTA. 2-3 variants.

Company voice (assume unless told otherwise): confident, plain-spoken, benefit-led,
no jargon, no LLM tics ("delve", "navigate the landscape").

When the user asks for a PDF deliverable (a one-pager, brochure, campaign brief, 小红书
layout, or anything they intend to save/share as a file), CALL the generate_pdf tool
with a clean title and 3-8 sections. After the tool returns, briefly tell the user the
PDF was generated — do NOT paste its full body back.

If a brief is missing context (audience, product), make one reasonable assumption and
note it.
"""


def run(
    client: anthropic.Anthropic,
    task: str,
    format: str,
    tone: str | None = None,
    audience: str | None = None,
    length_hint: str | None = None,
    on_event: Callable[[str, dict], None] | None = None,
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

    def handle_generate_pdf(payload: dict[str, Any]) -> str:
        result = generate_pdf(payload)
        # Register artifact in DB and emit trace event so the UI auto-selects it.
        try:
            from server import db  # local import to avoid circular at module load

            rec = db.add_artifact(
                session_id=None,  # session_id wiring happens via on_event in the route layer
                kind="pdf",
                filename=result["filename"],
                mime=result["mime"],
                path=result["path"],
            )
            if on_event:
                on_event(
                    "artifact_created",
                    {
                        "artifact_id": rec["id"],
                        "filename": rec["filename"],
                        "mime": rec["mime"],
                        "kind": rec["kind"],
                    },
                )
            return f"PDF generated. artifact_id={rec['id']}, filename={rec['filename']}"
        except Exception as exc:  # noqa: BLE001
            return f"PDF rendered to {result['path']} but artifact registration failed: {exc}"

    return run_agent(
        client=client,
        system=SYSTEM,
        user_message="\n".join(brief_lines),
        tools=[GENERATE_PDF_TOOL],
        client_tool_handlers={"generate_pdf": handle_generate_pdf},
    )
