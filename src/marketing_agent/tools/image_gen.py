"""Marketing image generation via Google Gemini (gemini-2.5-flash-image).

Isolates all google-genai SDK specifics behind ``generate_image``. The function
NEVER raises: a missing ``GEMINI_API_KEY``, an SDK error, a safety block, or an
empty response all degrade to an ``unavailable`` result dict so the server stays
up and tests can mock the SDK. DB writes happen in the route layer (which has the
authenticated ``user_id``), not here — mirroring how the analytics/research agents
keep API calls separate from persistence.
"""
from __future__ import annotations

import os
import uuid
from pathlib import Path

from dotenv import load_dotenv

from marketing_agent.config import PROJECT_ROOT

from ..agents.image_skills import ImageSkill

ARTIFACTS_DIR = PROJECT_ROOT / "tmp" / "artifacts"
GEMINI_MODEL = "gemini-2.5-flash-image"


def _api_key() -> str | None:
    key = os.environ.get("GEMINI_API_KEY")
    if key:
        return key
    # Be defensive for non-FastAPI entrypoints (tests, scripts, workers) that import
    # this module without going through ``server.main`` / CLI, where dotenv is loaded.
    load_dotenv(PROJECT_ROOT / ".env", override=False)
    return os.environ.get("GEMINI_API_KEY")


def unavailable_result(exc: Exception | None, *, feature: str = "image generation") -> dict:
    """Return a graceful failure result (never raised) for a failed/absent generation."""
    if exc is None:
        reason = (
            f"{feature} is not configured: set GEMINI_API_KEY on the server to enable "
            "marketing image generation."
        )
    else:
        message = str(exc) or exc.__class__.__name__
        lower = message.lower()
        if "resource_exhausted" in lower or "429" in lower or "quota" in lower:
            reason = (
                f"{feature} hit a Gemini quota/rate limit. The image model "
                "(gemini-2.5-flash-image) is not available on the free tier — enable billing "
                "on your Google AI Studio / Cloud project, or wait for the rate window to reset, "
                "then retry."
            )
        elif "api key" in lower or "api_key" in lower or "permission" in lower or "401" in lower:
            reason = f"{feature} rejected the request (check GEMINI_API_KEY): {message}"
        elif "safety" in lower or "blocked" in lower or "prohibited" in lower:
            reason = f"{feature} was blocked by the model's safety filters. Adjust the prompt and retry."
        else:
            reason = f"{feature} failed: {message}"
    return {
        "ok": False,
        "unavailable": True,
        "message": (
            f"## Image Unavailable\n\n{reason}\n\n"
            "The rest of the app is unaffected — fix the cause and retry."
        ),
    }


def _extract_png_bytes(response) -> bytes | None:
    """Pull the first inline image payload out of a google-genai response."""
    candidates = getattr(response, "candidates", None) or []
    for candidate in candidates:
        content = getattr(candidate, "content", None)
        parts = getattr(content, "parts", None) or []
        for part in parts:
            inline = getattr(part, "inline_data", None)
            if inline is not None and getattr(inline, "data", None):
                return inline.data
    return None


def _to_png(data: bytes) -> bytes:
    """Normalize any returned image bytes to PNG (Gemini usually returns PNG already)."""
    try:
        import io

        from PIL import Image

        with Image.open(io.BytesIO(data)) as im:
            if im.format == "PNG":
                return data
            buf = io.BytesIO()
            im.convert("RGBA").save(buf, format="PNG")
            return buf.getvalue()
    except Exception:  # noqa: BLE001 - if Pillow can't parse, persist raw bytes as-is
        return data


def build_prompt(prompt: str, skill: ImageSkill, aspect_ratio: str | None = None) -> str:
    ratio = aspect_ratio or skill.aspect_ratio
    return (
        f"{skill.prompt_prefix()} Target aspect ratio {ratio}. "
        f"Keep the uploaded product/subject faithful and recognizable. "
        f"User request: {prompt}"
    )


def _generate_raw(
    key: str, prompt_text: str, reference_images: list[tuple[bytes, str]] | None
) -> bytes | None:
    """All google-genai SDK specifics live here — the single seam tests monkeypatch.

    Returns raw image bytes from the model, or None if the response has no image.
    """
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=key)
    contents: list = [prompt_text]
    for data, mime in reference_images or []:
        contents.append(types.Part.from_bytes(data=data, mime_type=mime))
    response = client.models.generate_content(model=GEMINI_MODEL, contents=contents)
    return _extract_png_bytes(response)


def generate_image(
    prompt: str,
    *,
    skill: ImageSkill,
    reference_images: list[tuple[bytes, str]] | None = None,
    aspect_ratio: str | None = None,
) -> dict:
    """Generate a marketing image. Returns metadata on success or an unavailable dict.

    Success: ``{"ok": True, "filename", "mime": "image/png", "path", "png_bytes"}``.
    Failure/absent key: ``unavailable_result(...)`` (never raises).
    """
    key = _api_key()
    if not key:
        return unavailable_result(None)

    try:
        prompt_text = build_prompt(prompt, skill, aspect_ratio)
        raw = _generate_raw(key, prompt_text, reference_images)
        if not raw:
            return unavailable_result(RuntimeError("model returned no image"))
        png = _to_png(raw)
    except Exception as exc:  # noqa: BLE001 - degrade gracefully, never crash the server
        return unavailable_result(exc)

    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    artifact_id = uuid.uuid4().hex
    filename = f"marketing_{skill.key}.png"
    path = ARTIFACTS_DIR / f"{artifact_id}_{filename}"
    path.write_bytes(png)
    return {
        "ok": True,
        "filename": filename,
        "mime": "image/png",
        "path": str(path.resolve()),
        "png_bytes": png,
    }
