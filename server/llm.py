"""Shared DeepSeek client factory for server-side model calls.

Both the request path (`routes._client`) and the background long-term memory
extractor reuse this so client construction and the "no API key" behavior live
in one place. Returns ``None`` when unconfigured rather than raising, letting
callers decide whether that is fatal (routes) or a reason to degrade
gracefully (memory extraction falls back to heuristics).

The client is cached per process: it owns an HTTP connection pool, so rebuilding
it per request would pay a TLS handshake on every model call.
"""
from __future__ import annotations

import os
import threading

from marketing_agent import llm_client

_LOCK = threading.Lock()
_CLIENT: llm_client.DeepSeek | None = None
_CLIENT_KEY: str | None = None


def get_client() -> llm_client.DeepSeek | None:
    global _CLIENT, _CLIENT_KEY

    api_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        return None

    with _LOCK:
        # Rebuild if the key changed (tests swap it in and out).
        if _CLIENT is None or _CLIENT_KEY != api_key:
            _CLIENT = llm_client.DeepSeek(api_key=api_key)
            _CLIENT_KEY = api_key
        return _CLIENT
