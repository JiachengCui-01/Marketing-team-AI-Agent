"""Local cross-encoder reranker for knowledge-base retrieval.

A cross-encoder scores each (query, passage) pair jointly, which is far more
accurate than the bi-encoder recall step — but too slow to run over the whole
corpus, so it only reranks the fused top candidates. Loaded lazily; degrades to a
no-op (callers keep the fused order) when unavailable.
"""
from __future__ import annotations

import logging
import os
import threading

logger = logging.getLogger(__name__)

_FALSEY = {"0", "false", "no", "off", ""}
# Multilingual MS MARCO cross-encoder reranker.
DEFAULT_MODEL = os.environ.get(
    "MARKETING_AGENT_RERANK_MODEL", "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"
)

_LOCK = threading.Lock()
_MODEL = None
_LOAD_FAILED = False


def enabled() -> bool:
    """Reranking enabled? Default on; set MARKETING_AGENT_KB_RERANK=0 to skip."""
    return os.environ.get("MARKETING_AGENT_KB_RERANK", "1").strip().lower() not in _FALSEY


def _get_model():
    global _MODEL, _LOAD_FAILED
    if _MODEL is not None or _LOAD_FAILED:
        return _MODEL
    with _LOCK:
        if _MODEL is not None or _LOAD_FAILED:
            return _MODEL
        try:
            from sentence_transformers import CrossEncoder

            _MODEL = CrossEncoder(DEFAULT_MODEL)
            logger.info("loaded reranker model %s", DEFAULT_MODEL)
        except Exception:  # noqa: BLE001
            _LOAD_FAILED = True
            logger.warning("reranker unavailable; keeping fused order", exc_info=True)
    return _MODEL


def is_available() -> bool:
    if not enabled():
        return False
    return _get_model() is not None


def rerank(query: str, passages: list[str]) -> list[float] | None:
    """Return a relevance score per passage, or ``None`` if unavailable."""
    if not passages or not enabled():
        return None
    model = _get_model()
    if model is None:
        return None
    try:
        scores = model.predict([(query, p) for p in passages])
        return [float(s) for s in scores]
    except Exception:  # noqa: BLE001
        logger.warning("rerank failed", exc_info=True)
        return None


def reset_for_tests() -> None:
    global _MODEL, _LOAD_FAILED
    with _LOCK:
        _MODEL = None
        _LOAD_FAILED = False
