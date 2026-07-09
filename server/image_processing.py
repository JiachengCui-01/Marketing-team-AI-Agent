"""Subject detection + background cutout for the marketing image feature.

Two steps:
1. ``classify_subject`` — a cheap Claude vision call that decides whether the upload
   is a distinct physical object (worth cutting out) or an app/UI screenshot (keep
   whole). Defaults to 'screenshot' on any ambiguity, which is the safe, non-destructive
   choice (no cutout is applied).
2. ``cutout`` — local ``rembg`` (u2net) background removal → transparent PNG. rembg and
   Pillow are imported lazily inside the function so the heavy onnxruntime import cost is
   only paid on first use (mirrors how pdf_tool imports reportlab lazily).
"""
from __future__ import annotations

import base64

import anthropic

from marketing_agent.config import MODEL_ID


class CutoutUnavailable(RuntimeError):
    """Raised when rembg cutout fails (missing dep, model download, or inference error)."""


_CLASSIFY_SYSTEM = (
    "You classify a single uploaded image for a marketing-image pipeline. "
    "Reply with EXACTLY ONE lowercase word and nothing else:\n"
    "- 'object' if the image is a distinct physical product/object photographed against "
    "some background (so the background could be removed to isolate the subject).\n"
    "- 'screenshot' if the image is an app/website/software UI screenshot, a poster, a "
    "document, or anything where the whole frame should be preserved.\n"
    "If unsure, answer 'screenshot'."
)


def classify_subject(client: anthropic.Anthropic, image_bytes: bytes, media_type: str) -> str:
    """Return 'object' or 'screenshot'. Defaults to 'screenshot' on any ambiguity/error."""
    try:
        data_b64 = base64.standard_b64encode(image_bytes).decode("ascii")
        response = client.messages.create(
            model=MODEL_ID,
            max_tokens=8,
            system=_CLASSIFY_SYSTEM,
            output_config={"effort": "low"},
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": data_b64,
                            },
                        },
                        {"type": "text", "text": "Classify this image."},
                    ],
                }
            ],
        )
        text = "".join(b.text for b in response.content if b.type == "text").strip().lower()
        return "object" if "object" in text else "screenshot"
    except Exception:  # noqa: BLE001 - classification never blocks the flow
        return "screenshot"


def cutout(image_bytes: bytes) -> bytes:
    """Remove the background with rembg → transparent PNG bytes. Raises CutoutUnavailable."""
    try:
        from rembg import remove  # lazy: onnxruntime import is heavy
    except Exception as exc:  # noqa: BLE001
        raise CutoutUnavailable(f"rembg is unavailable: {exc}") from exc
    try:
        result = remove(image_bytes)
        if not result:
            raise CutoutUnavailable("rembg returned empty output")
        return result
    except CutoutUnavailable:
        raise
    except Exception as exc:  # noqa: BLE001
        raise CutoutUnavailable(f"cutout failed: {exc}") from exc


def process_upload(client: anthropic.Anthropic, image_bytes: bytes, media_type: str) -> dict:
    """Classify then (for objects) cut out.

    Returns ``{"classification": 'object'|'screenshot', "original_png": bytes,
    "cutout_png": bytes | None, "warning": str | None}``. Cutout is only attempted for
    'object'; a cutout failure degrades to ``cutout_png=None`` + a warning (never raises).
    """
    classification = classify_subject(client, image_bytes, media_type)
    cutout_png: bytes | None = None
    warning: str | None = None
    if classification == "object":
        try:
            cutout_png = cutout(image_bytes)
        except CutoutUnavailable as exc:
            warning = str(exc)
    return {
        "classification": classification,
        "original_png": image_bytes,
        "cutout_png": cutout_png,
        "warning": warning,
    }
