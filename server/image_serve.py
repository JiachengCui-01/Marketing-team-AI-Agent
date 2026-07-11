"""On-the-fly preview optimization for images.

Full-size generated PNGs are ~1 MB, which render top-to-bottom over the wire. For
inline previews we downscale + recompress once and cache the result to disk so the
browser gets a small, fast-loading image. Opaque images become progressive JPEGs
(they paint whole rather than line-by-line); images with alpha stay optimized PNG.

Falls back to the original file if Pillow is unavailable or the source is not a
raster image (e.g. PDF), so previews never break.
"""
from __future__ import annotations

from pathlib import Path

from marketing_agent.config import PROJECT_ROOT

CACHE_DIR = PROJECT_ROOT / "tmp" / "preview_cache"
MAX_EDGE = 1600
JPEG_QUALITY = 82


def optimized_preview(src_path: str, cache_key: str) -> tuple[str, str]:
    """Return ``(path, media_type)`` for an optimized preview of ``src_path``.

    ``cache_key`` should be a stable, filesystem-safe id (artifact/upload id). The
    original file is returned unchanged for non-images or on any failure.
    """
    src = Path(src_path)
    suffix = src.suffix.lower()
    if suffix not in {".png", ".jpg", ".jpeg", ".webp"}:
        return src_path, _mime_for(suffix)

    try:
        from PIL import Image

        with Image.open(src) as im:
            im.load()
            has_alpha = _has_visible_alpha(im)
            if max(im.size) > MAX_EDGE:
                im.thumbnail((MAX_EDGE, MAX_EDGE), Image.LANCZOS)

            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            if has_alpha:
                out = CACHE_DIR / f"{cache_key}.png"
                if not out.exists():
                    im.convert("RGBA").save(out, format="PNG", optimize=True)
                return str(out), "image/png"

            out = CACHE_DIR / f"{cache_key}.jpg"
            if not out.exists():
                im.convert("RGB").save(
                    out, format="JPEG", quality=JPEG_QUALITY, progressive=True, optimize=True
                )
            return str(out), "image/jpeg"
    except Exception:  # noqa: BLE001 - never let preview optimization break serving
        return src_path, _mime_for(suffix)


def _mime_for(suffix: str) -> str:
    return {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
    }.get(suffix, "application/octet-stream")


def _has_visible_alpha(im) -> bool:
    """Return true only when the image contains at least one transparent pixel."""
    if im.mode in {"RGBA", "LA"}:
        alpha = im.getchannel("A")
        return alpha.getextrema()[0] < 255
    if im.mode == "P" and "transparency" in im.info:
        alpha = im.convert("RGBA").getchannel("A")
        return alpha.getextrema()[0] < 255
    return False
