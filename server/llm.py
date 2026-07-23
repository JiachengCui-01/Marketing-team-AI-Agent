"""Shared Anthropic client factory for server-side model calls.

Both the request path (`routes._client`) and the background long-term memory
extractor reuse this so client construction and the "no API key" behavior live
in one place. Returns ``None`` when unconfigured rather than raising, letting
callers decide whether that is fatal (routes) or a reason to degrade
gracefully (memory extraction falls back to heuristics).
"""
from __future__ import annotations

import os

import anthropic


def get_client() -> anthropic.Anthropic | None:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None
    return anthropic.Anthropic()
