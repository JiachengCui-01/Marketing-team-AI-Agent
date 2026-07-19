"""PDF generation tool — produces a styled PDF artifact and registers it in the DB."""
from __future__ import annotations

import uuid
from datetime import date
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from marketing_agent.config import PROJECT_ROOT

ARTIFACTS_DIR = PROJECT_ROOT / "tmp" / "artifacts"
PDF_FONT_NAME = "STSong-Light"
PDF_BOLD_FONT_NAME = "STSong-Light"
BRAND_NAVY = "#172033"
BRAND_ACCENT = "#4f46e5"
BRAND_MUTED = "#667085"
BRAND_LINE = "#d9dee8"
BRAND_SOFT = "#f4f6fb"


def _register_fonts(pdfmetrics, UnicodeCIDFont, TTFont) -> tuple[str, str]:
    font_candidates = [
        ("MarketingSans", "MarketingSansBold", Path("C:/Windows/Fonts/msyh.ttc"), Path("C:/Windows/Fonts/msyhbd.ttc")),
        ("MarketingSans", "MarketingSansBold", Path("C:/Windows/Fonts/NotoSansSC-VF.ttf"), Path("C:/Windows/Fonts/NotoSansSC-VF.ttf")),
        ("MarketingSans", "MarketingSansBold", Path("C:/Windows/Fonts/simhei.ttf"), Path("C:/Windows/Fonts/simhei.ttf")),
    ]
    for regular_name, bold_name, regular_path, bold_path in font_candidates:
        if not regular_path.exists() or not bold_path.exists():
            continue
        try:
            if regular_name not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(TTFont(regular_name, str(regular_path), subfontIndex=0))
            if bold_name not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(TTFont(bold_name, str(bold_path), subfontIndex=0))
            return regular_name, bold_name
        except Exception:  # noqa: BLE001 - fall back to built-in CJK CID font
            continue

    if PDF_FONT_NAME not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(UnicodeCIDFont(PDF_FONT_NAME))
    return PDF_FONT_NAME, PDF_BOLD_FONT_NAME


def _paragraph_text(value: Any) -> str:
    return escape(str(value or "")).replace("\n", "<br/>")


def _inline_text(value: Any) -> str:
    text = escape(str(value or "").strip())
    text = text.replace("**", "")
    text = text.replace("__", "")
    text = text.replace("`", "")
    return text


def _is_table_separator(line: str) -> bool:
    cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
    return bool(cells) and all(cell and set(cell) <= {"-", ":"} for cell in cells)


def _is_table_line(line: str) -> bool:
    return "|" in line and len(line.strip().strip("|").split("|")) >= 2


def _table_rows(lines: list[str]) -> list[list[str]]:
    rows: list[list[str]] = []
    for line in lines:
        if _is_table_separator(line):
            continue
        rows.append([_inline_text(cell) for cell in line.strip().strip("|").split("|")])
    return rows


def _flush_paragraph(buffer: list[str], story: list[Any], style: Any) -> None:
    if not buffer:
        return
    text = " ".join(part.strip() for part in buffer if part.strip())
    if text:
        story.append(style["Paragraph"](_inline_text(text), style["body"]))
    buffer.clear()


def _body_flowables(body: str, styles: dict[str, Any], table_width: float) -> list[Any]:
    from reportlab.lib import colors
    from reportlab.platypus import Paragraph, Spacer, Table, TableStyle

    out: list[Any] = []
    paragraph_buffer: list[str] = []
    lines = body.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index].rstrip()
        stripped = line.strip()

        if not stripped:
            _flush_paragraph(paragraph_buffer, out, {**styles, "Paragraph": Paragraph})
            out.append(Spacer(1, 5))
            index += 1
            continue

        if _is_table_line(stripped) and index + 1 < len(lines) and _is_table_separator(lines[index + 1]):
            _flush_paragraph(paragraph_buffer, out, {**styles, "Paragraph": Paragraph})
            table_lines = [stripped, lines[index + 1].strip()]
            index += 2
            while index < len(lines) and _is_table_line(lines[index].strip()):
                table_lines.append(lines[index].strip())
                index += 1
            rows = _table_rows(table_lines)
            if rows:
                max_cols = max(len(row) for row in rows)
                normalized = [row + [""] * (max_cols - len(row)) for row in rows]
                table_data = [
                    [Paragraph(cell, styles["table_header" if row_index == 0 else "table_cell"]) for cell in row]
                    for row_index, row in enumerate(normalized)
                ]
                col_width = table_width / max_cols
                table = Table(table_data, colWidths=[col_width] * max_cols, repeatRows=1, hAlign="LEFT")
                table.setStyle(
                    TableStyle(
                        [
                            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(BRAND_NAVY)),
                            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                            ("BACKGROUND", (0, 1), (-1, -1), colors.white),
                            ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor(BRAND_LINE)),
                            ("VALIGN", (0, 0), (-1, -1), "TOP"),
                            ("LEFTPADDING", (0, 0), (-1, -1), 7),
                            ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                            ("TOPPADDING", (0, 0), (-1, -1), 6),
                            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                        ]
                    )
                )
                out.append(table)
                out.append(Spacer(1, 10))
            continue

        bullet_match = stripped.startswith(("- ", "* "))
        numbered_match = stripped[:2].replace(".", "").replace(")", "").isdigit() and (
            ". " in stripped[:5] or ") " in stripped[:5]
        )
        if bullet_match or numbered_match:
            _flush_paragraph(paragraph_buffer, out, {**styles, "Paragraph": Paragraph})
            rows: list[list[Any]] = []
            ordered = numbered_match
            number = 1
            while index < len(lines):
                item = lines[index].strip()
                is_bullet = item.startswith(("- ", "* "))
                is_number = item[:2].replace(".", "").replace(")", "").isdigit() and (
                    ". " in item[:5] or ") " in item[:5]
                )
                if ordered and not is_number:
                    break
                if not ordered and not is_bullet:
                    break
                content = item[2:].strip() if is_bullet else item.split(" ", 1)[1].strip()
                marker = f"{number}." if ordered else "-"
                rows.append([
                    Paragraph(marker, styles["list_marker"]),
                    Paragraph(_inline_text(content), styles["body"]),
                ])
                number += 1
                index += 1
            list_table = Table(rows, colWidths=[20, table_width - 20], hAlign="LEFT")
            list_table.setStyle(
                TableStyle(
                    [
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("LEFTPADDING", (0, 0), (-1, -1), 0),
                        ("RIGHTPADDING", (0, 0), (0, -1), 6),
                        ("RIGHTPADDING", (1, 0), (1, -1), 0),
                        ("TOPPADDING", (0, 0), (-1, -1), 2),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                    ]
                )
            )
            out.append(list_table)
            out.append(Spacer(1, 7))
            continue

        paragraph_buffer.append(stripped)
        index += 1

    _flush_paragraph(paragraph_buffer, out, {**styles, "Paragraph": Paragraph})
    return out


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
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import inch, mm
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.cidfonts import UnicodeCIDFont
        from reportlab.pdfbase.ttfonts import TTFont
        from reportlab.platypus import (
            SimpleDocTemplate,
            Paragraph,
            Spacer,
            PageBreak,
            HRFlowable,
            KeepTogether,
        )
    except ImportError as exc:
        raise RuntimeError("reportlab is required for generate_pdf; pip install reportlab") from exc

    regular_font, bold_font = _register_fonts(pdfmetrics, UnicodeCIDFont, TTFont)

    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    artifact_id = uuid.uuid4().hex
    safe_title = "".join(c if c.isalnum() or c in "-_ " else "_" for c in payload.get("title") or "document").strip()[:60] or "document"
    filename = f"{safe_title}.pdf"
    path = ARTIFACTS_DIR / f"{artifact_id}_{filename}"

    report_date = payload.get("date") or date.today().strftime("%Y-%m-%d")
    eyebrow = payload.get("eyebrow") or "Marketing Strategy Deliverable"
    title = payload.get("title", "Untitled")
    subtitle = payload.get("subtitle") or ""

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "TitleBig",
        parent=styles["Title"],
        fontName=bold_font,
        fontSize=30,
        leading=37,
        textColor=colors.HexColor(BRAND_NAVY),
        alignment=0,
        spaceAfter=14,
    )
    subtitle_style = ParagraphStyle(
        "Sub",
        parent=styles["Normal"],
        fontName=regular_font,
        fontSize=12.5,
        leading=18,
        textColor=colors.HexColor(BRAND_MUTED),
        spaceAfter=18,
    )
    heading_style = ParagraphStyle(
        "H",
        parent=styles["Heading2"],
        fontName=bold_font,
        fontSize=15,
        leading=20,
        textColor=colors.HexColor(BRAND_NAVY),
        spaceBefore=18,
        spaceAfter=8,
    )
    body_style = ParagraphStyle(
        "Body",
        parent=styles["BodyText"],
        fontName=regular_font,
        fontSize=10.5,
        leading=16,
        textColor=colors.HexColor("#273043"),
        spaceAfter=8,
    )
    eyebrow_style = ParagraphStyle(
        "Eyebrow",
        parent=styles["Normal"],
        fontName=bold_font,
        fontSize=9,
        leading=12,
        textColor=colors.HexColor(BRAND_ACCENT),
        spaceAfter=18,
    )
    meta_style = ParagraphStyle(
        "Meta",
        parent=styles["Normal"],
        fontName=regular_font,
        fontSize=9.5,
        leading=13,
        textColor=colors.HexColor(BRAND_MUTED),
    )
    section_label_style = ParagraphStyle(
        "SectionLabel",
        parent=styles["Normal"],
        fontName=bold_font,
        fontSize=8.5,
        leading=11,
        textColor=colors.HexColor(BRAND_ACCENT),
        spaceAfter=2,
    )
    table_header_style = ParagraphStyle(
        "TableHeader",
        parent=styles["Normal"],
        fontName=bold_font,
        fontSize=8.5,
        leading=11,
        textColor=colors.white,
    )
    table_cell_style = ParagraphStyle(
        "TableCell",
        parent=styles["Normal"],
        fontName=regular_font,
        fontSize=8.2,
        leading=11,
        textColor=colors.HexColor("#273043"),
    )
    list_marker_style = ParagraphStyle(
        "ListMarker",
        parent=styles["Normal"],
        fontName=bold_font,
        fontSize=9.2,
        leading=16,
        textColor=colors.HexColor(BRAND_ACCENT),
        alignment=2,
    )

    doc = SimpleDocTemplate(
        str(path),
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title=str(title),
        author="Marketing Agent",
    )
    doc.report_title = str(title)  # type: ignore[attr-defined]
    story: list[Any] = []
    story.append(Spacer(1, 0.12 * inch))
    story.append(Paragraph(_inline_text(eyebrow).upper(), eyebrow_style))
    story.append(Paragraph(_paragraph_text(title), title_style))
    if subtitle:
        story.append(Paragraph(_paragraph_text(subtitle), subtitle_style))
    story.append(
        HRFlowable(
            width="100%",
            thickness=1.2,
            color=colors.HexColor(BRAND_ACCENT),
            spaceBefore=4,
            spaceAfter=18,
        )
    )
    story.append(Paragraph(f"Generated {report_date} - Confidential working draft", meta_style))
    story.append(Spacer(1, 0.32 * inch))

    sections = payload.get("sections", [])
    if sections:
        first_body = str(sections[0].get("body", "") or "")
        if first_body:
            summary = first_body.splitlines()[0][:520]
            story.append(KeepTogether([
                Paragraph("Executive snapshot", section_label_style),
                Paragraph(_inline_text(summary), subtitle_style),
            ]))
            story.append(Spacer(1, 0.16 * inch))
    story.append(PageBreak())

    render_styles = {
        "body": body_style,
        "list_marker": list_marker_style,
        "table_header": table_header_style,
        "table_cell": table_cell_style,
    }
    for index, sec in enumerate(sections, start=1):
        heading = sec.get("heading", "") or f"Section {index}"
        story.append(KeepTogether([
            Paragraph(f"{index:02d}", section_label_style),
            Paragraph(_paragraph_text(heading), heading_style),
        ]))
        story.extend(_body_flowables(str(sec.get("body", "") or ""), render_styles, doc.width))

    def draw_page(canvas, document) -> None:
        canvas.saveState()
        width, height = A4
        canvas.setStrokeColor(colors.HexColor(BRAND_LINE))
        canvas.setLineWidth(0.45)
        canvas.line(document.leftMargin, height - 12 * mm, width - document.rightMargin, height - 12 * mm)
        canvas.setFont(regular_font, 8)
        canvas.setFillColor(colors.HexColor(BRAND_MUTED))
        canvas.drawString(document.leftMargin, height - 9 * mm, "Marketing Agent")
        canvas.drawRightString(width - document.rightMargin, height - 9 * mm, str(getattr(document, "report_title", ""))[:70])
        canvas.line(document.leftMargin, 11 * mm, width - document.rightMargin, 11 * mm)
        canvas.drawString(document.leftMargin, 7 * mm, "Confidential")
        canvas.drawRightString(width - document.rightMargin, 7 * mm, f"Page {document.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=draw_page, onLaterPages=draw_page)

    return {
        "artifact_id": artifact_id,
        "filename": filename,
        "mime": "application/pdf",
        "path": str(path.resolve()),
    }
