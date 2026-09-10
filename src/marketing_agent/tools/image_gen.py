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


def _bullets(header: str, items: tuple[str, ...] | list[str]) -> str:
    return "\n".join([header, *(f"- {item}" for item in items)])


# Fidelity block, only sent when the user attached a photo. The model's instinct with
# a furniture reference is to "improve" the design — restyle the arms, drop a leg,
# shift the wood tone — and a listing image of a product we do not sell is worse than
# no image at all.
_SUBJECT_FIDELITY_HEADER = (
    "SUBJECT FIDELITY\nThe attached photo is the ACTUAL product being sold. "
    "Reproduce it exactly:"
)
_SUBJECT_FIDELITY_RULES = (
    "Identical silhouette, proportions, and stance.",
    "Identical materials, finish color, wood grain pattern, fabric weave, and sheen.",
    "Identical part counts and details — legs, cushions, drawers, shelves, handles, "
    "stitching lines, and hardware finish.",
    "You may re-light it, change the camera angle within reason, and rebuild the "
    "background or room around it.",
    "You may not redesign it, restyle it, recolor it, swap its material, add or remove "
    "parts, or replace it with a similar-looking piece.",
    "If the attached photo is poorly lit or shot in a messy room, fix the lighting and "
    "the surroundings — never the product itself.",
)

# Re-edit is a different relationship to the attachment: it is our own previous
# render, and the whole point of the turn is to change something about it. The
# product-fidelity wording above would refuse the edit that was just asked for.
_PRIOR_RENDER_HEADER = (
    "EDIT SCOPE\nThe attached image is the previous render of this product. Apply the "
    "requested change and nothing else:"
)
_PRIOR_RENDER_RULES = (
    "Keep the product's design, materials, finish color, proportions, and part counts "
    "exactly as they appear — unless the request explicitly asks to change one of them.",
    "Keep the composition, camera angle, and lighting unless the request asks otherwise.",
    "Re-render at full quality; do not crop in, add a border, or degrade sharpness.",
)

REFERENCE_PRODUCT = "product"
REFERENCE_PRIOR_RENDER = "prior_render"
_REFERENCE_BLOCKS = {
    REFERENCE_PRODUCT: (_SUBJECT_FIDELITY_HEADER, _SUBJECT_FIDELITY_RULES),
    REFERENCE_PRIOR_RENDER: (_PRIOR_RENDER_HEADER, _PRIOR_RENDER_RULES),
}


def build_prompt(
    prompt: str,
    skill: ImageSkill,
    aspect_ratio: str | None = None,
    *,
    reference: str = "",
) -> str:
    """Assemble the image prompt from the channel spec plus the user's own request.

    An empty ``prompt`` is normal and expected: the user picked a channel style and
    attached a photo, which is already a complete brief. The style's
    ``default_request`` then stands in for the typed request rather than the call
    being refused.

    Sections are ordered and their authority is stated explicitly, because the two
    inputs genuinely conflict sometimes — "put it in a living room" against an Amazon
    main image is a request for a listing that gets suppressed. Platform rules win,
    the rest of the request still lands.
    """
    ratio = aspect_ratio or skill.aspect_ratio
    request = (prompt or "").strip()
    blocks = [
        f"TASK\nProduce one production-ready {skill.label} image for a US DTC brand "
        "that designs its own large furniture and freight-ships it to US customers. "
        "The result must be publishable on that channel exactly as delivered, with no "
        "retouching step afterwards.",
        f"OUTPUT SPEC\n- Aspect ratio: {ratio}\n- Render detail for {skill.pixel_target}"
        "\n- One single image — not a grid, collage, or before/after pair",
    ]
    if skill.platform_rules:
        blocks.append(_bullets(
            "PLATFORM RULES — non-negotiable, they decide whether the channel accepts "
            "the image:", skill.platform_rules,
        ))
    blocks.append(_bullets(
        "ART DIRECTION — our house look; the request below overrides any of these it "
        "contradicts:", skill.art_direction,
    ))
    blocks.append(f"BACKGROUND\n{skill.background_guidance}.")
    blocks.append(_bullets(
        "DELIVERY QUALITY — an image failing any of these is unusable:",
        skill.all_delivery_rules(),
    ))
    if reference in _REFERENCE_BLOCKS:
        header, rules = _REFERENCE_BLOCKS[reference]
        blocks.append(_bullets(header, rules))
    if request:
        blocks.append(f"REQUEST FROM THE MARKETER\n{request}")
    else:
        blocks.append(
            "REQUEST FROM THE MARKETER\nNone given — the marketer selected this "
            f"channel style and expects its default deliverable:\n{skill.default_request}"
        )
    blocks.append(
        "PRECEDENCE\n1. Platform rules. 2. Subject fidelity to the attached product. "
        "3. The request from the marketer. 4. Art direction. Where the request "
        "conflicts with a platform rule, satisfy the platform rule and still honor "
        "every part of the request that does not conflict — do not discard the request."
    )
    if skill.negative_hints:
        blocks.append("AVOID\n" + ", ".join(skill.negative_hints) + ".")
    return "\n\n".join(blocks)


def _image_config(aspect_ratio: str):
    """Ask the SDK to enforce the aspect ratio, when this version supports it.

    Prompt text alone does not reliably control the output ratio, and a 16:9 hero
    delivered as a square is unusable as a banner. Older google-genai releases have
    no ``ImageConfig``; there the prompt's OUTPUT SPEC is all we have.
    """
    from google.genai import types

    if not hasattr(types, "ImageConfig") or not hasattr(types, "GenerateContentConfig"):
        return None
    try:
        return types.GenerateContentConfig(
            image_config=types.ImageConfig(aspect_ratio=aspect_ratio)
        )
    except Exception:  # noqa: BLE001 — unknown field/ratio in this SDK version
        return None


def _generate_raw(
    key: str,
    prompt_text: str,
    reference_images: list[tuple[bytes, str]] | None,
    aspect_ratio: str | None = None,
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
    config = _image_config(aspect_ratio) if aspect_ratio else None
    if config is not None:
        try:
            response = client.models.generate_content(
                model=GEMINI_MODEL, contents=contents, config=config
            )
            return _extract_png_bytes(response)
        except Exception as exc:  # noqa: BLE001 — ratio unsupported for this model
            if not _is_image_config_rejection(exc):
                raise
    response = client.models.generate_content(model=GEMINI_MODEL, contents=contents)
    return _extract_png_bytes(response)


def _is_image_config_rejection(exc: Exception) -> bool:
    """Only swallow the failure mode the bare retry can actually fix."""
    message = str(exc).lower()
    return any(
        marker in message
        for marker in ("image_config", "imageconfig", "aspect_ratio", "aspect ratio")
    )


def generate_image(
    prompt: str,
    *,
    skill: ImageSkill,
    reference_images: list[tuple[bytes, str]] | None = None,
    aspect_ratio: str | None = None,
    reference_kind: str = REFERENCE_PRODUCT,
) -> dict:
    """Generate a marketing image. Returns metadata on success or an unavailable dict.

    Success: ``{"ok": True, "filename", "mime": "image/png", "path", "png_bytes"}``.
    Failure/absent key: ``unavailable_result(...)`` (never raises).
    """
    key = _api_key()
    if not key:
        return unavailable_result(None)

    ratio = aspect_ratio or skill.aspect_ratio
    try:
        prompt_text = build_prompt(
            prompt, skill, ratio,
            reference=reference_kind if reference_images else "",
        )
        raw = _generate_raw(key, prompt_text, reference_images, ratio)
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
