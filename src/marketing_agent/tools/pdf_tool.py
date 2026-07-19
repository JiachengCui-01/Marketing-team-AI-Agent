"""PDF generation tool — produces a styled PDF artifact and registers it in the DB."""
from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from marketing_agent.config import PROJECT_ROOT

ARTIFACTS_DIR = PROJECT_ROOT / "tmp" / "artifacts"
PDF_FONT_NAME = "STSong-Light"


def _paragraph_text(value: Any) -> str:
    return escape(str(value or "")).replace("\n", "<br/>")


GENERATE_PDF_TOOL = {
    "name": "generate_pdf",
    "description": (
        "Render a multi-section marketing PDF and return an artifact id the user can "
        "preview and download. Use this when the user asks for a PDF deliverable "
        "(brochure, one-pager, campaign brief, 小红书 post layout, etc.)."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Document title shown on the cover."},
            "subtitle": {"type": "string", "description": "Optional subtitle / tagline."},
            "sections": {
                "type": "array",
                "description": "Ordered list of body sections.",
                "items": {
                    "type": "object",
                    "properties": {
                        "heading": {"type": "string"},
                        "body": {"type": "string", "description": "Markdown-light paragraph text."},
                    },
                    "required": ["heading", "body"],
                },
            },
        },
        "required": ["title", "sections"],
    },
}


def generate_pdf(payload: dict[str, Any]) -> dict[str, Any]:
    """Render the PDF to tmp/artifacts and return artifact metadata.

    Returns dict with keys: artifact_id, filename, mime, path.
    """
    try:
        from reportlab.lib.pagesizes import LETTER
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import inch
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.cidfonts import UnicodeCIDFont
        from reportlab.platypus import (
            SimpleDocTemplate,
            Paragraph,
            Spacer,
            PageBreak,
        )
    except ImportError as exc:
        raise RuntimeError("reportlab is required for generate_pdf; pip install reportlab") from exc

    if PDF_FONT_NAME not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(UnicodeCIDFont(PDF_FONT_NAME))

    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    artifact_id = uuid.uuid4().hex
    safe_title = "".join(c if c.isalnum() or c in "-_ " else "_" for c in payload.get("title") or "document").strip()[:60] or "document"
    filename = f"{safe_title}.pdf"
    path = ARTIFACTS_DIR / f"{artifact_id}_{filename}"

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "TitleBig",
        parent=styles["Title"],
        fontName=PDF_FONT_NAME,
        fontSize=28,
        leading=34,
        spaceAfter=12,
    )
    subtitle_style = ParagraphStyle(
        "Sub",
        parent=styles["Normal"],
        fontName=PDF_FONT_NAME,
        fontSize=14,
        textColor="#666666",
        spaceAfter=24,
    )
    heading_style = ParagraphStyle(
        "H",
        parent=styles["Heading2"],
        fontName=PDF_FONT_NAME,
        fontSize=16,
        spaceBefore=18,
        spaceAfter=8,
    )
    body_style = ParagraphStyle(
        "Body",
        parent=styles["BodyText"],
        fontName=PDF_FONT_NAME,
        fontSize=11,
        leading=16,
        spaceAfter=10,
    )

    doc = SimpleDocTemplate(
        str(path),
        pagesize=LETTER,
        leftMargin=0.9 * inch,
        rightMargin=0.9 * inch,
        topMargin=1 * inch,
        bottomMargin=1 * inch,
    )
    story: list[Any] = []
    story.append(Paragraph(_paragraph_text(payload.get("title", "Untitled")), title_style))
    if payload.get("subtitle"):
        story.append(Paragraph(_paragraph_text(payload["subtitle"]), subtitle_style))
    story.append(Spacer(1, 0.2 * inch))

    for sec in payload.get("sections", []):
        story.append(Paragraph(_paragraph_text(sec.get("heading", "")), heading_style))
        story.append(Paragraph(_paragraph_text(sec.get("body", "")), body_style))

    doc.build(story)

    return {
        "artifact_id": artifact_id,
        "filename": filename,
        "mime": "application/pdf",
        "path": str(path.resolve()),
    }
