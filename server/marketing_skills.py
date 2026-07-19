"""Filesystem-backed marketing SOP skills."""
from __future__ import annotations

from pathlib import Path

from marketing_agent.config import PROJECT_ROOT

SKILLS_DIR = PROJECT_ROOT / "skills"
MAX_SKILL_TEXT_CHARS = 18_000
PDF_DELIVERABLE_SKILLS = {"competitive-positioning-brief"}


def _read(path: Path, limit: int = MAX_SKILL_TEXT_CHARS) -> str:
    return path.read_text(encoding="utf-8", errors="replace")[:limit]


def _first_section(markdown: str) -> tuple[str, str]:
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
    return title, " ".join(description)


def list_skills() -> list[dict]:
    if not SKILLS_DIR.exists():
        return []
    out: list[dict] = []
    for skill_dir in sorted(p for p in SKILLS_DIR.iterdir() if p.is_dir()):
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.exists():
            continue
        text = _read(skill_md, 4000)
        name, description = _first_section(text)
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


def build_skill_addendum(skill_ids: list[str]) -> str:
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
            for ref in sorted(ref_dir.glob("*.md"))[:4]:
                parts.append(f"### Reference: {ref.name}\n{_read(ref, 6000)}")
        chunks.append("\n\n".join(parts))
    if not chunks:
        return ""
    return (
        "\n\n[Selected marketing SOP skills]\n"
        "Follow the selected SOP skill(s) below when producing the answer. "
        "If required inputs are missing, ask concise clarifying questions before making strong assumptions.\n\n"
        "If a selected skill requires a PDF deliverable, the final answer must include a generated PDF artifact.\n\n"
        + "\n\n---\n\n".join(chunks)
    )[:MAX_SKILL_TEXT_CHARS]
