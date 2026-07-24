"""Local sentence-transformers embeddings for knowledge-base semantic search.

The model is heavy (torch), so it is imported and loaded lazily and only once.
Everything degrades gracefully: if ``sentence-transformers`` is not installed, the
env switch is off, or loading fails, ``is_available()`` returns ``False`` and callers
fall back to lexical retrieval.
"""
from __future__ import annotations

import logging
import os
import threading

logger = logging.getLogger(__name__)

_FALSEY = {"0", "false", "no", "off", ""}
# Multilingual (zh + en) sentence model, 384-dim, ~120MB.
DEFAULT_MODEL = os.environ.get(
    "MARKETING_AGENT_EMBED_MODEL", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
)

_LOCK = threading.Lock()
_MODEL = None  # loaded SentenceTransformer or None
_LOAD_FAILED = False


def enabled() -> bool:
    """Semantic embeddings enabled? Default on; set MARKETING_AGENT_KB_SEMANTIC=0 to skip
    the heavy model load (used by tests / offline runs)."""
    return os.environ.get("MARKETING_AGENT_KB_SEMANTIC", "1").strip().lower() not in _FALSEY


def _get_model():
    global _MODEL, _LOAD_FAILED
    if _MODEL is not None or _LOAD_FAILED:
        return _MODEL
    with _LOCK:
        if _MODEL is not None or _LOAD_FAILED:
            return _MODEL
        try:
            from sentence_transformers import SentenceTransformer

            _MODEL = SentenceTransformer(DEFAULT_MODEL)
            logger.info("loaded embedding model %s", DEFAULT_MODEL)
        except Exception:  # noqa: BLE001
            _LOAD_FAILED = True
            logger.warning("embedding model unavailable; falling back to lexical retrieval", exc_info=True)
    return _MODEL


def is_available() -> bool:
    if not enabled():
        return False
    return _get_model() is not None


def embed_texts(texts: list[str]) -> list[list[float]] | None:
    """Embed a batch of texts. Returns ``None`` if embeddings are unavailable."""
    if not texts or not enabled():
        return None
    model = _get_model()
    if model is None:
        return None
    try:
        vectors = model.encode(texts, normalize_embeddings=True, convert_to_numpy=True)
        return [v.tolist() for v in vectors]
    except Exception:  # noqa: BLE001
        logger.warning("embedding failed", exc_info=True)
        return None


def embed_one(text: str) -> list[float] | None:
    out = embed_texts([text])
    return out[0] if out else None


def reset_for_tests() -> None:
    global _MODEL, _LOAD_FAILED
    with _LOCK:
        _MODEL = None
        _LOAD_FAILED = False
