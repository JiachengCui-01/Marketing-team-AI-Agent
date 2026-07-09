"""File upload handling — CSV, PDF, Word, and images.

Files are saved to tmp/uploads/ keyed by a UUID file_id.
"""
from __future__ import annotations

import re
import uuid
from pathlib import Path

from marketing_agent.config import PROJECT_ROOT

UPLOAD_DIR = PROJECT_ROOT / "tmp" / "uploads"
MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB

ALLOWED_EXT = {".csv", ".xlsx", ".xls", ".json", ".pdf", ".docx", ".png", ".jpg", ".jpeg", ".webp"}

EXT_MIME = {
    ".csv": "text/csv",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".xls": "application/vnd.ms-excel",
    ".json": "application/json",
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}

_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


class UploadValidationError(ValueError):
    """Raised when an uploaded file fails safety validation."""


def _ensure_dir() -> None:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


def sanitize_filename(original_name: str) -> tuple[str, str]:
    """Return (safe_name, ext_lower). Raises if extension not allowed."""
    name = Path(original_name).name.strip()
    if not name:
        raise UploadValidationError("Missing filename.")
    ext = Path(name).suffix.lower()
    if ext not in ALLOWED_EXT:
        raise UploadValidationError(
            f"Unsupported file type '{ext}'. Allowed: {', '.join(sorted(ALLOWED_EXT))}"
        )
    safe_stem = _SAFE_NAME_RE.sub("_", Path(name).stem).strip("._")
    if not safe_stem:
        raise UploadValidationError("Invalid filename.")
    safe_name = f"{safe_stem}{ext}"[:160]
    return safe_name, ext


def validate(content: bytes, original_name: str) -> tuple[str, str]:
    if not content:
        raise UploadValidationError("Empty file.")
    if len(content) > MAX_UPLOAD_BYTES:
        raise UploadValidationError(
            f"File exceeds the {MAX_UPLOAD_BYTES // (1024 * 1024)} MB upload limit."
        )
    return sanitize_filename(original_name)


def save(content: bytes, original_name: str, content_type: str | None = None) -> dict:
    _ensure_dir()
    safe_name, ext = validate(content, original_name)
    file_id = uuid.uuid4().hex
    target = UPLOAD_DIR / f"{file_id}_{safe_name}"
    target.write_bytes(content)
    return {
        "file_id": file_id,
        "original_name": safe_name,
        "size": len(content),
        "mime": EXT_MIME.get(ext, content_type or "application/octet-stream"),
        "ext": ext,
    }


def resolve(file_id: str) -> Path | None:
    """Return the absolute path matching a file_id, or None if not found."""
    if not re.fullmatch(r"[0-9a-f]{32}", file_id):
        return None
    _ensure_dir()
    for path in UPLOAD_DIR.glob(f"{file_id}_*"):
        if path.is_file():
            return path.resolve()
    return None
