"""Extract text or image references from uploaded files for agent prompts."""
from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

MAX_TEXT_CHARS = 60_000  # cap inlined text to avoid blowing the prompt


def _read_pdf(path: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:
        return f"[pdf extraction unavailable — install pypdf to read {path.name}]"
    try:
        reader = PdfReader(str(path))
        parts = []
        for i, page in enumerate(reader.pages):
            try:
                parts.append(page.extract_text() or "")
            except Exception:  # noqa: BLE001
                parts.append(f"[page {i + 1} extraction failed]")
        return "\n\n".join(parts)
    except Exception as exc:  # noqa: BLE001
        return f"[failed to read pdf {path.name}: {exc}]"


def _docx_paragraph_markdown(paragraph, qn) -> str:
    """Paragraph text as markdown, preserving in-paragraph line breaks and mapping
    Word heading/list styles to ``#``/``-`` so the structure survives extraction."""
    parts: list[str] = []
    for node in paragraph._element.iter():
        if node.tag == qn("w:t"):
            parts.append(node.text or "")
        elif node.tag in (qn("w:br"), qn("w:cr")):
            parts.append("\n")
        elif node.tag == qn("w:tab"):
            parts.append("\t")
    text = "\n".join(line.rstrip() for line in "".join(parts).splitlines()).strip()
    if not text:
        return ""
    style = (paragraph.style.name or "").lower() if paragraph.style else ""
    if style.startswith("heading"):
        try:
            level = min(max(int(style.split()[-1]), 1), 6)
        except ValueError:
            level = 2
        return f"{'#' * level} {text}"
    if style.startswith("list"):
        return f"- {text}"
    return text


def _docx_table_markdown(table) -> str:
    """Render a Word table as a GitHub-flavored markdown table (with a header
    separator row) so it survives as a table instead of being dropped."""
    rows = [["" if c.text is None else " ".join(c.text.split()) for c in r.cells] for r in table.rows]
    rows = [r for r in rows if any(cell for cell in r)]
    if not rows:
        return ""
    ncols = max(len(r) for r in rows)
    lines = ["| " + " | ".join((r + [""] * ncols)[:ncols]) + " |" for r in rows]
    separator = "| " + " | ".join(["---"] * ncols) + " |"
    return "\n".join([lines[0], separator, *lines[1:]])


def _read_docx(path: Path) -> str:
    try:
        import docx  # python-docx
        from docx.oxml.ns import qn
        from docx.table import Table
        from docx.text.paragraph import Paragraph
    except ImportError:
        return f"[docx extraction unavailable — install python-docx to read {path.name}]"
    try:
        document = docx.Document(str(path))
        blocks: list[str] = []
        # Walk the body in document order so tables keep their position and are not
        # dropped (``document.paragraphs`` omits table cells entirely). Blocks are
        # joined with blank lines so headings/tables parse as markdown, not one blob.
        for child in document.element.body.iterchildren():
            if child.tag == qn("w:p"):
                md = _docx_paragraph_markdown(Paragraph(child, document), qn)
            elif child.tag == qn("w:tbl"):
                md = _docx_table_markdown(Table(child, document))
            else:
                md = ""
            if md.strip():
                blocks.append(md)
        return "\n\n".join(blocks).strip()
    except Exception as exc:  # noqa: BLE001
        return f"[failed to read docx {path.name}: {exc}]"


def _read_csv(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:  # noqa: BLE001
        return f"[failed to read csv {path.name}: {exc}]"


def extract(path: Path) -> dict[str, Any]:
    """Return a dict describing the file's content for use in a prompt.

    Returns one of:
      {"kind": "text", "name": ..., "ext": ..., "text": "..."}
      {"kind": "image", "name": ..., "media_type": ..., "data_b64": "..."}
    """
    ext = path.suffix.lower()
    name = path.name
    if ext == ".pdf":
        text = _read_pdf(path)[:MAX_TEXT_CHARS]
        return {"kind": "text", "name": name, "ext": ext, "text": text}
    if ext == ".docx":
        text = _read_docx(path)[:MAX_TEXT_CHARS]
        return {"kind": "text", "name": name, "ext": ext, "text": text}
    if ext == ".csv":
        text = _read_csv(path)[:MAX_TEXT_CHARS]
        return {"kind": "text", "name": name, "ext": ext, "text": text}
    if ext in {".png", ".jpg", ".jpeg", ".webp"}:
        media_type = {".png": "image/png", ".webp": "image/webp"}.get(ext, "image/jpeg")
        data_b64 = base64.standard_b64encode(path.read_bytes()).decode("ascii")
        return {"kind": "image", "name": name, "media_type": media_type, "data_b64": data_b64}
    # Fallback: treat as text
    try:
        text = path.read_text(encoding="utf-8", errors="replace")[:MAX_TEXT_CHARS]
    except Exception as exc:  # noqa: BLE001
        text = f"[unreadable: {exc}]"
    return {"kind": "text", "name": name, "ext": ext, "text": text}


def build_prompt_addendum(extracted: list[dict[str, Any]]) -> str:
    """Compose a text block describing attached files for inclusion in the prompt."""
    if not extracted:
        return ""
    parts = ["\n\n---\nAttached files:"]
    for f in extracted:
        if f["kind"] == "text":
            parts.append(f"\n### {f['name']}\n```\n{f['text']}\n```")
        elif f["kind"] == "image":
            parts.append(f"\n### {f['name']} (image attached separately)")
    return "\n".join(parts)
