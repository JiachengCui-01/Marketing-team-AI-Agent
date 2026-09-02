"""Extract text or image references from uploaded files for agent prompts."""
from __future__ import annotations

import base64
import re
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

MAX_TEXT_CHARS = 60_000  # cap inlined text to avoid blowing the prompt
MAX_EXCEL_CHUNK_CHARS = 1_800


def _cap_excel_chunks(chunks: list[str]) -> list[str]:
    """Keep workbook ingestion inside the same prompt/embedding ceiling as documents."""
    kept: list[str] = []
    used = 0
    for chunk in chunks:
        remaining = MAX_TEXT_CHARS - used
        if remaining <= 0:
            break
        value = chunk[:remaining]
        if value.strip():
            kept.append(value)
            used += len(value)
    return kept


def _cell_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return " ".join(str(value).replace("\r", "\n").split())


def _nonempty_regions(rows: list[list[str]]) -> list[tuple[int, int, int, int]]:
    """Connected non-empty cell regions as (top, left, bottom, right).

    Blank rows/columns naturally separate a KPI block, instructions, and a main
    table.  Four-way connectivity deliberately keeps diagonally separated blocks
    apart; they are usually independent cards or flowchart annotations.
    """
    cells = {
        (r, c)
        for r, row in enumerate(rows)
        for c, value in enumerate(row)
        if value.strip()
    }
    regions: list[tuple[int, int, int, int]] = []
    while cells:
        seed = cells.pop()
        stack = [seed]
        component = [seed]
        while stack:
            r, c = stack.pop()
            for nxt in ((r - 1, c), (r + 1, c), (r, c - 1), (r, c + 1)):
                if nxt in cells:
                    cells.remove(nxt)
                    stack.append(nxt)
                    component.append(nxt)
        regions.append((
            min(r for r, _ in component), min(c for _, c in component),
            max(r for r, _ in component), max(c for _, c in component),
        ))
    return sorted(regions)


def _excel_col(index: int) -> str:
    value = index + 1
    letters = ""
    while value:
        value, rem = divmod(value - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


def _render_excel_region(
    workbook: str,
    sheet: str,
    rows: list[list[str]],
    bounds: tuple[int, int, int, int],
) -> list[str]:
    """Render one data island, row-chunking large tables and repeating its header."""
    top, left, bottom, right = bounds
    region = [[rows[r][c] if c < len(rows[r]) else "" for c in range(left, right + 1)]
              for r in range(top, bottom + 1)]
    coord = f"{_excel_col(left)}{top + 1}:{_excel_col(right)}{bottom + 1}"
    prefix = f"[Excel: {workbook}]\n[工作表/Sheet: {sheet} | 区域/Range: {coord}]"

    # A single cell or a narrow text island is narrative content, not a table.
    if len(region) == 1 or max(len(row) for row in region) == 1:
        body = "\n".join(cell for row in region for cell in row if cell)
        return [f"{prefix}\n{body}"[:MAX_EXCEL_CHUNK_CHARS]] if body else []

    def line(row: list[str]) -> str:
        return " | ".join(cell or "—" for cell in row).rstrip()

    header = line(region[0])
    chunks: list[str] = []
    current = f"{prefix}\n{header}"
    for row in region[1:]:
        rendered = line(row)
        if len(current) + len(rendered) + 1 > MAX_EXCEL_CHUNK_CHARS:
            chunks.append(current)
            current = f"{prefix}\n表头/Header: {header}\n{rendered}"
        else:
            current += "\n" + rendered
    if current.strip() != prefix:
        chunks.append(current)
    return chunks


def _drawing_anchor(node: ET.Element) -> tuple[int, int]:
    ns = {"xdr": "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing"}
    anchor = node.find("xdr:from", ns)
    if anchor is None:
        return (10**9, 10**9)
    row = anchor.find("xdr:row", ns)
    col = anchor.find("xdr:col", ns)
    return (int(row.text or 0) if row is not None else 0,
            int(col.text or 0) if col is not None else 0)


def _pack_diagram_lines(prefix: str, lines: list[str]) -> list[str]:
    """Pack a large diagram without dropping its tail; repeat context per chunk."""
    chunks: list[str] = []
    current = prefix
    for line in lines:
        if len(current) + len(line) + 1 > MAX_EXCEL_CHUNK_CHARS:
            if current != prefix:
                chunks.append(current)
            current = prefix + "\n" + line
        else:
            current += "\n" + line
    if current != prefix:
        chunks.append(current)
    return chunks


def _extract_xlsx_diagrams(path: Path) -> list[str]:
    """Extract editable Excel shapes/SmartArt and connector relationships.

    openpyxl intentionally drops most drawing objects.  Reading the OOXML parts
    directly preserves the labels that carry the meaning of process diagrams.
    Embedded raster screenshots remain non-textual and are explicitly noted.
    """
    chunks: list[str] = []
    try:
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
            drawing_to_sheet: dict[str, str] = {}
            workbook_names: list[str] = []
            if "xl/workbook.xml" in names:
                root = ET.fromstring(archive.read("xl/workbook.xml"))
                workbook_names = [
                    str(node.attrib.get("name") or f"Sheet {i + 1}")
                    for i, node in enumerate(root.iter()) if node.tag.endswith("}sheet")
                ]
            for i, sheet in enumerate(workbook_names, 1):
                rel_path = f"xl/worksheets/_rels/sheet{i}.xml.rels"
                if rel_path not in names:
                    continue
                rel_root = ET.fromstring(archive.read(rel_path))
                for rel in rel_root:
                    target = str(rel.attrib.get("Target") or "")
                    if "drawings/" in target:
                        drawing_to_sheet["xl/" + target.replace("../", "")] = sheet

            ns = {
                "xdr": "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing",
                "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
            }
            for drawing in sorted(n for n in names if re.fullmatch(r"xl/drawings/drawing\d+\.xml", n)):
                root = ET.fromstring(archive.read(drawing))
                nodes: list[tuple[tuple[int, int], str, str, str]] = []
                connectors: list[tuple[str, str]] = []
                for anchor in root:
                    pos = _drawing_anchor(anchor)
                    for shape in anchor.findall(".//xdr:sp", ns):
                        meta = shape.find(".//xdr:cNvPr", ns)
                        sid = str(meta.attrib.get("id") or "") if meta is not None else ""
                        name = str(meta.attrib.get("name") or "") if meta is not None else ""
                        text = " ".join((n.text or "").strip() for n in shape.findall(".//a:t", ns) if (n.text or "").strip())
                        if text:
                            nodes.append((pos, sid, name, text))
                    for conn in anchor.findall(".//xdr:cxnSp", ns):
                        start = conn.find(".//a:stCxn", ns)
                        end = conn.find(".//a:endCxn", ns)
                        if start is not None and end is not None:
                            connectors.append((str(start.attrib.get("id") or ""), str(end.attrib.get("id") or "")))
                if nodes:
                    nodes.sort(key=lambda item: item[0])
                    labels = {sid: text for _, sid, _name, text in nodes}
                    prefix = "\n".join([
                        f"[Excel: {path.name}]",
                        f"[工作表/Sheet: {drawing_to_sheet.get(drawing, 'unknown')} | 流程图/Diagram]",
                    ])
                    node_lines = [
                        f"节点/Node {sid or name}: {text}" for _pos, sid, name, text in nodes
                    ]
                    flow_lines = [
                            f"连接/Flow: {labels.get(start, start or '?')} -> {labels.get(end, end or '?')}"
                        for start, end in connectors
                    ]
                    chunks.extend(_pack_diagram_lines(prefix + "\n[节点/Nodes]", node_lines))
                    chunks.extend(_pack_diagram_lines(prefix + "\n[连接关系/Flows]", flow_lines))

            # SmartArt text/relationships live outside drawing*.xml.
            for diagram in sorted(n for n in names if re.fullmatch(r"xl/diagrams/data\d+\.xml", n)):
                root = ET.fromstring(archive.read(diagram))
                points: dict[str, str] = {}
                relations: list[tuple[str, str]] = []
                for node in root.iter():
                    if node.tag.endswith("}pt"):
                        model_id = str(node.attrib.get("modelId") or "")
                        label = " ".join(
                            (child.text or "").strip() for child in node.iter()
                            if child.tag.endswith("}t") and (child.text or "").strip()
                        )
                        if model_id and label:
                            points[model_id] = label
                    elif node.tag.endswith("}cxn"):
                        source = str(node.attrib.get("srcId") or "")
                        target = str(node.attrib.get("destId") or "")
                        if source and target:
                            relations.append((source, target))
                if points:
                    prefix = f"[Excel: {path.name}]\n[SmartArt / 流程图]"
                    node_lines = [f"节点/Node {pid}: {label}" for pid, label in points.items()]
                    flow_lines = [
                        f"连接/Flow: {points.get(source, source)} -> {points.get(target, target)}"
                        for source, target in relations
                    ]
                    chunks.extend(_pack_diagram_lines(prefix + "\n[节点/Nodes]", node_lines))
                    chunks.extend(_pack_diagram_lines(prefix + "\n[连接关系/Flows]", flow_lines))
    except (OSError, zipfile.BadZipFile, ET.ParseError):
        return []
    return chunks


def _read_xlsx(path: Path) -> tuple[str, list[str]]:
    try:
        import openpyxl
    except ImportError:
        message = f"[xlsx extraction unavailable — install openpyxl to read {path.name}]"
        return message, [message]
    try:
        workbook = openpyxl.load_workbook(str(path), data_only=False, read_only=False)
        chunks: list[str] = []
        for sheet in workbook.worksheets:
            rows = [[_cell_text(cell.value) for cell in row] for row in sheet.iter_rows()]
            while rows and not any(rows[-1]):
                rows.pop()
            if not rows:
                continue
            width = max((len(row) for row in rows), default=0)
            rows = [row + [""] * (width - len(row)) for row in rows]
            for region in _nonempty_regions(rows):
                chunks.extend(_render_excel_region(path.name, sheet.title, rows, region))
        chunks.extend(_extract_xlsx_diagrams(path))
        chunks = _cap_excel_chunks(chunks)
        text = "\n\n".join(chunks)[:MAX_TEXT_CHARS]
        return text, chunks
    except Exception as exc:  # noqa: BLE001
        message = f"[failed to read xlsx {path.name}: {exc}]"
        return message, [message]


def _read_xls(path: Path) -> tuple[str, list[str]]:
    try:
        import xlrd
    except ImportError:
        message = f"[xls extraction unavailable — install xlrd to read {path.name}]"
        return message, [message]
    try:
        workbook = xlrd.open_workbook(str(path), on_demand=True)
        chunks: list[str] = []
        for sheet in workbook.sheets():
            rows = [[_cell_text(sheet.cell_value(r, c)) for c in range(sheet.ncols)]
                    for r in range(sheet.nrows)]
            for region in _nonempty_regions(rows):
                chunks.extend(_render_excel_region(path.name, sheet.name, rows, region))
        chunks = _cap_excel_chunks(chunks)
        text = "\n\n".join(chunks)[:MAX_TEXT_CHARS]
        return text, chunks
    except Exception as exc:  # noqa: BLE001
        message = f"[failed to read xls {path.name}: {exc}]"
        return message, [message]


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
    if ext == ".xlsx":
        text, chunks = _read_xlsx(path)
        return {"kind": "text", "name": name, "ext": ext, "text": text, "chunks": chunks}
    if ext == ".xls":
        text, chunks = _read_xls(path)
        return {"kind": "text", "name": name, "ext": ext, "text": text, "chunks": chunks}
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
