"""CSV upload handling.

Files are saved to tmp/uploads/ keyed by a UUID file_id. The route layer owns
HTTP status codes; this module keeps validation and filesystem behavior stable.
"""
from __future__ import annotations

import re
import uuid
from pathlib import Path

from marketing_agent.config import PROJECT_ROOT

UPLOAD_DIR = PROJECT_ROOT / "tmp" / "uploads"
MAX_UPLOAD_BYTES = 2 * 1024 * 1024
ALLOWED_CONTENT_TYPES = {
    "text/csv",
    "application/csv",
    "application/vnd.ms-excel",
    "text/plain",
}

_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


class UploadValidationError(ValueError):
    """Raised when an uploaded file fails CSV safety validation."""


def _ensure_dir() -> None:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


def sanitize_filename(original_name: str) -> str:
    """Return a filesystem-safe CSV filename stripped of path components."""
    name = Path(original_name).name.strip()
    if not name:
        raise UploadValidationError("Missing filename.")
    if Path(name).suffix.lower() != ".csv":
        raise UploadValidationError("Only .csv files are supported.")

    safe_name = _SAFE_NAME_RE.sub("_", name).strip("._")
    if not safe_name or safe_name.lower() == "csv":
        raise UploadValidationError("Invalid filename.")
    if not safe_name.lower().endswith(".csv"):
        safe_name = f"{safe_name}.csv"
    return safe_name[:120]


def validate(content: bytes, original_name: str, content_type: str | None = None) -> str:
    """Validate upload metadata/content and return the sanitized filename."""
    if not content:
        raise UploadValidationError("Empty file.")
    if len(content) > MAX_UPLOAD_BYTES:
        raise UploadValidationError(
            f"CSV exceeds the {MAX_UPLOAD_BYTES // (1024 * 1024)} MB upload limit."
        )
    if content_type and content_type.lower() not in ALLOWED_CONTENT_TYPES:
        raise UploadValidationError("Only CSV uploads are supported.")
    return sanitize_filename(original_name)


def save(content: bytes, original_name: str, content_type: str | None = None) -> dict:
    _ensure_dir()
    safe_name = validate(content, original_name, content_type)
    file_id = uuid.uuid4().hex
    target = UPLOAD_DIR / f"{file_id}_{safe_name}"
    target.write_bytes(content)
    return {
        "file_id": file_id,
        "original_name": safe_name,
        "size": len(content),
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
