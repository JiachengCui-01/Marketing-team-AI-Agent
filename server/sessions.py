"""In-memory session store.

Single-process, single-user MVP storage with TTL and capacity bounds. This keeps
the development server from retaining unbounded conversation history.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
import uuid

from marketing_agent.conversation import Conversation

SESSION_TTL_SECONDS = 4 * 60 * 60
MAX_SESSIONS = 50


@dataclass
class StoredSession:
    conversation: Conversation
    created_at: float = field(default_factory=time.monotonic)
    accessed_at: float = field(default_factory=time.monotonic)


_SESSIONS: dict[str, StoredSession] = {}


def _prune(now: float | None = None) -> None:
    now = time.monotonic() if now is None else now
    expired = [
        session_id
        for session_id, stored in _SESSIONS.items()
        if now - stored.accessed_at > SESSION_TTL_SECONDS
    ]
    for session_id in expired:
        _SESSIONS.pop(session_id, None)

    overflow = len(_SESSIONS) - MAX_SESSIONS
    if overflow > 0:
        oldest = sorted(_SESSIONS.items(), key=lambda item: item[1].accessed_at)
        for session_id, _ in oldest[:overflow]:
            _SESSIONS.pop(session_id, None)


def create() -> str:
    _prune()
    session_id = uuid.uuid4().hex
    _SESSIONS[session_id] = StoredSession(Conversation())
    _prune()
    return session_id


def get(session_id: str) -> Conversation | None:
    _prune()
    stored = _SESSIONS.get(session_id)
    if stored is None:
        return None
    stored.accessed_at = time.monotonic()
    return stored.conversation


def delete(session_id: str) -> bool:
    return _SESSIONS.pop(session_id, None) is not None


def exists(session_id: str) -> bool:
    _prune()
    return session_id in _SESSIONS


def reset_for_tests() -> None:
    _SESSIONS.clear()
