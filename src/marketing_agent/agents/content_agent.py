"""Content generation agent — channel-specific marketing copy and PDF deliverables."""
from __future__ import annotations

from typing import Any, Callable

import anthropic

from ..tools.pdf_tool import GENERATE_PDF_TOOL, generate_pdf
from .base import run_agent
from .content_skills import select_content_skill

SYSTEM = """You are a senior B2B marketing copywriter on an enterprise marketing team.
You write crisp, on-brand copy by following the selected platform skill in the brief.

Company voice (assume unless told otherwise): confident, plain-spoken, benefit-led,
no jargon, no LLM tics ("delve", "navigate the landscape").

When the selected platform skill or user task asks for a PDF deliverable, CALL the
generate_pdf tool. After the tool returns, briefly tell the user the PDF was generated.
If the brief explicitly asks for an in-chat analysis or SOP-style answer, include that
analysis in the response as well; otherwise do not paste the full PDF body back.

If a brief is missing context (audience, product), make one reasonable assumption and
note it.
"""


def _output_language_for_task(task: str) -> str:
    lowered = task.lower()
    explicit_en = any(token in lowered for token in ("english", "in en", "write in en", "英文", "英语"))
    explicit_zh = any(token in lowered for token in ("chinese", "simplified chinese", "中文", "简体中文", "汉语"))
    if explicit_en and not explicit_zh:
        return "en"
    if explicit_zh and not explicit_en:
        return "zh"
    cjk = sum(1 for char in task if "\u4e00" <= char <= "\u9fff")
    letters = sum(1 for char in task if char.isalpha())
    return "zh" if cjk >= max(2, letters // 5) else "en"


def run(
    client: anthropic.Anthropic,
    task: str,
    format: str,
    platform: str | None = None,
    tone: str | None = None,
    audience: str | None = None,
    length_hint: str | None = None,
    on_event: Callable[[str, dict], None] | None = None,
) -> str:
    skill = select_content_skill(format, task, platform)
    output_language = _output_language_for_task(task)
    language_instruction = (
        "Output language: Simplified Chinese. The chat response and any generated PDF "
        "must use Simplified Chinese for titles, headings, tables, and body content, "
        "unless the user explicitly requested another language."
        if output_language == "zh"
        else "Output language: English. The chat response and any generated PDF must use "
        "English for titles, headings, tables, and body content, unless the user explicitly "
        "requested another language."
    )
    brief_lines = [
        f"Task: {task}",
        f"Format: {format}",
        f"Selected platform skill: {skill.key}",
        language_instruction,
        "",
        skill.render(),
    ]
    if platform:
        brief_lines.append(f"Requested platform: {platform}")
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
