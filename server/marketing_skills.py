"""Filesystem-backed marketing SOP skills."""
from __future__ import annotations

from pathlib import Path, PurePosixPath
import io
import re
import stat
import tempfile
import zipfile

from marketing_agent.config import PROJECT_ROOT

SKILLS_DIR = PROJECT_ROOT / "skills"
MAX_SKILL_TEXT_CHARS = 18_000
PDF_DELIVERABLE_SKILLS = {"competitive-positioning-brief"}
MAX_ARCHIVE_BYTES = 10 * 1024 * 1024
MAX_EXTRACTED_BYTES = 30 * 1024 * 1024
MAX_ARCHIVE_FILES = 200


def install_skill_archive(data: bytes, filename: str) -> dict:
    """Validate and stage one ZIP skill before atomically publishing it."""
    if not filename.lower().endswith(".zip"):
        raise ValueError("Please upload a .zip skill archive.")
    if len(data) > MAX_ARCHIVE_BYTES:
        raise ValueError("ZIP exceeds the 10 MB upload limit.")
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            entries = archive.infolist()
            if len(entries) > MAX_ARCHIVE_FILES:
                raise ValueError("ZIP contains more than 200 entries.")
            files: dict[PurePosixPath, zipfile.ZipInfo] = {}
            seen: set[str] = set()
            total = 0
            for entry in entries:
                raw = entry.orig_filename
                path = PurePosixPath(raw)
                if (not raw or "\\" in raw or path.is_absolute()
                        or any(part in (".", "..") for part in raw.split("/") if part)
                        or any(re.search(r'[<>:"|?*\x00-\x1f]', part)
                               or part.endswith((".", " "))
                               or part.split(".")[0].upper() in
                               {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
                               for part in path.parts)):
                    raise ValueError("ZIP contains an unsafe file path.")
                mode = entry.external_attr >> 16
                if stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR):
                    raise ValueError("ZIP links and special files are not supported.")
                if entry.flag_bits & 1:
                    raise ValueError("Encrypted ZIP files are not supported.")
                key = str(path).casefold()
                if key in seen:
                    raise ValueError("ZIP contains duplicate file paths.")
                seen.add(key)
                total += entry.file_size
                if total > MAX_EXTRACTED_BYTES:
                    raise ValueError("Uncompressed ZIP exceeds the 30 MB limit.")
                if not entry.is_dir() and "__MACOSX" not in path.parts and path.name != ".DS_Store":
                    files[path] = entry
            roots = [p.parent for p in files if p.name == "SKILL.md"]
            if len(roots) != 1:
                raise ValueError("ZIP must contain exactly one SKILL.md.")
            root = roots[0]
            if any(not p.is_relative_to(root) for p in files):
                raise ValueError("All skill files must be inside the SKILL.md folder.")
            file_keys = {str(p).casefold() for p in files}
            for path in files:
                if any(str(parent).casefold() in file_keys for parent in path.parents):
                    raise ValueError("ZIP contains conflicting file and directory paths.")
            if any(str(root / folder).casefold() in file_keys for folder in ("references", "scripts", "assets")):
                raise ValueError("references, scripts and assets must be directories.")
            source_name = root.name or Path(filename).stem
            skill_id = re.sub(r"[^a-z0-9_-]+", "-", source_name.lower()).strip("-_")[:80]
            if not skill_id:
                raise ValueError("Use an English folder or ZIP name for the skill ID.")
            SKILLS_DIR.mkdir(parents=True, exist_ok=True)
            target = SKILLS_DIR / skill_id
            if any(p.name.casefold() == skill_id.casefold() for p in SKILLS_DIR.iterdir()):
                raise FileExistsError("A skill with this ID already exists. Rename the skill folder or ZIP.")
            with tempfile.TemporaryDirectory(prefix=".skill-upload-", dir=SKILLS_DIR) as staging:
                staged = Path(staging) / skill_id
                staged.mkdir()
                for path, entry in files.items():
                    dest = staged.joinpath(*path.relative_to(root).parts)
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes(archive.read(entry))
                try:
                    instructions = (staged / "SKILL.md").read_text(encoding="utf-8-sig")
                except UnicodeDecodeError as exc:
                    raise ValueError("SKILL.md must use UTF-8 encoding.") from exc
                if not instructions.strip():
                    raise ValueError("SKILL.md must not be empty.")
                for folder in ("references", "scripts", "assets"):
                    (staged / folder).mkdir(exist_ok=True)
                staged.rename(target)
            return next(s for s in list_skills() if s["id"] == skill_id)
    except (zipfile.BadZipFile, NotImplementedError, RuntimeError) as exc:
        raise ValueError("Invalid or unsupported ZIP archive.") from exc


def _read(path: Path, limit: int = MAX_SKILL_TEXT_CHARS) -> str:
    return path.read_text(encoding="utf-8-sig", errors="replace")[:limit]


def _first_section(markdown: str) -> tuple[str, str]:
    # Read common scalar frontmatter fields without treating metadata as code.
    frontmatter = re.match(r"\A---\s*\n(.*?)\n---\s*(?:\n|$)", markdown, re.DOTALL)
    metadata: dict[str, str] = {}
    if frontmatter:
        for field in ("name", "description"):
            match = re.search(rf"^{field}:\s*([^\n]*)(?:\n((?:[ \t]+[^\n]*\n?)*))", frontmatter[1] + "\n", re.MULTILINE)
            if match:
                value = match[1].strip()
                if value in ("|", ">", "|-", ">-", "|+", ">+"):
                    value = " ".join((match[2] or "").split())
                metadata[field] = value.strip("\"'")
        markdown = markdown[frontmatter.end():]
    lines = [line.strip() for line in markdown.splitlines()]
    title = "Untitled skill"
    description: list[str] = []
    for line in lines:
        if line.startswith("# "):
            title = line[2:].strip() or title
            continue
        if title != "Untitled skill" and line and not line.startswith("#"):
            description.append(line)
        if len(description) >= 2:
            break
    return metadata.get("name") or title, metadata.get("description") or " ".join(description)


def list_skills() -> list[dict]:
    if not SKILLS_DIR.exists():
        return []
    out: list[dict] = []
    for skill_dir in sorted(p for p in SKILLS_DIR.iterdir() if p.is_dir() and not p.name.startswith(".")):
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.exists():
            continue
        text = _read(skill_md, 4000)
        name, description = _first_section(text)
        if name == "Untitled skill":
            name = skill_dir.name
        out.append(
            {
                "id": skill_dir.name,
                "name": name,
                "description": description,
                "structure": ["SKILL.md", "scripts", "references", "assets"],
                "requires_pdf": skill_dir.name in PDF_DELIVERABLE_SKILLS,
            }
        )
    return out


def selected_skill_names(skill_ids: list[str]) -> list[str]:
    skills = {skill["id"]: skill["name"] for skill in list_skills()}
    return [skills[sid] for sid in skill_ids if sid in skills]


def requires_pdf_deliverable(skill_ids: list[str]) -> bool:
    return any(sid in PDF_DELIVERABLE_SKILLS for sid in skill_ids)


def build_skill_addendum(skill_ids: list[str], output_language: str | None = None) -> str:
    if not skill_ids:
        return ""
    chunks: list[str] = []
    known = {skill["id"] for skill in list_skills()}
    for sid in skill_ids:
        if sid not in known:
            continue
        skill_dir = SKILLS_DIR / sid
        parts = [f"## Skill: {sid}", _read(skill_dir / "SKILL.md")]
        ref_dir = skill_dir / "references"
        if ref_dir.exists():
            for ref in sorted(ref_dir.rglob("*.md"))[:4]:
                parts.append(f"### Reference: {ref.name}\n{_read(ref, 6000)}")
        chunks.append("\n\n".join(parts))
    if not chunks:
        return ""
    language_instruction = ""
    if output_language == "zh":
        language_instruction = (
            "Unless the user explicitly requested another deliverable language, write all generated deliverables, "
            "including PDF titles, headings, tables, and body content, in Simplified Chinese.\n\n"
        )
    elif output_language == "en":
        language_instruction = (
            "Unless the user explicitly requested another deliverable language, write all generated deliverables, "
            "including PDF titles, headings, tables, and body content, in English.\n\n"
        )
    return (
        "\n\n[Selected marketing SOP skills]\n"
        "Follow the selected SOP skill(s) below when producing the answer. "
        "If required inputs are missing, ask concise clarifying questions before making strong assumptions.\n\n"
        + language_instruction
        + "If a selected skill requires a PDF deliverable, the final answer must still include a detailed in-chat "
        "analysis that follows the skill SOP; the PDF is a companion deliverable, not a replacement for the answer. "
        "Do not answer only with a file-generated notice.\n\n"
        + "\n\n---\n\n".join(chunks)
    )[:MAX_SKILL_TEXT_CHARS]
