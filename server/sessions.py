"""SQLite-backed session store with in-memory Conversation cache.

The Conversation object lives in memory for the duration of a live stream so the
orchestrator can append assistant turns to it directly. Every user/assistant
turn is also persisted to SQLite via add_message() so sessions survive restarts.
"""
from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field

from marketing_agent.conversation import Conversation

from . import db, memory


@dataclass
class StoredSession:
    conversation: Conversation


_CACHE: dict[str, StoredSession] = {}
_CACHE_LOCK = threading.Lock()


def _hydrate(session_id: str, user_id: str | None = None) -> Conversation | None:
    """Load message history from SQLite into a fresh Conversation."""
    if db.get_session(session_id, user_id) is None:
        return None
    if user_id is not None:
        return memory.build_conversation(session_id, user_id)
    conv = Conversation()
    for row in db.list_messages(session_id):
        content = row["content"]
        # Assistant content is JSON-encoded (list of blocks); user content is plain text or a JSON list.
        try:
            parsed = json.loads(content)
            conv.messages.append({"role": row["role"], "content": parsed})
        except (json.JSONDecodeError, TypeError):
            conv.messages.append({"role": row["role"], "content": content})
    return conv


def create(user_id: str, name: str = "New chat", group_id: str | None = None) -> str:
    rec = db.create_session(user_id=user_id, name=name, group_id=group_id)
    with _CACHE_LOCK:
        _CACHE[rec["id"]] = StoredSession(Conversation())
    return rec["id"]


def get(session_id: str, user_id: str | None = None) -> Conversation | None:
    if user_id is not None and db.get_session(session_id, user_id) is None:
        return None
    with _CACHE_LOCK:
        stored = _CACHE.get(session_id)
        if stored is not None:
            return stored.conversation
    conv = _hydrate(session_id, user_id)
    if conv is None:
        return None
    with _CACHE_LOCK:
        _CACHE[session_id] = StoredSession(conv)
        return _CACHE[session_id].conversation


def prepare_for_turn(session_id: str, user_id: str) -> Conversation | None:
    """Rebuild a compact working context before a model call.

    The full transcript remains in SQLite. The in-memory Conversation is a
    budgeted view with long-term profile, compressed older history, and recent
    turns.
    """
    conv = memory.build_conversation(session_id, user_id)
    if conv is None:
        return None
    with _CACHE_LOCK:
        _CACHE[session_id] = StoredSession(conv)
        return conv


def delete(session_id: str, user_id: str | None = None) -> bool:
    with _CACHE_LOCK:
        _CACHE.pop(session_id, None)
    return db.delete_session(session_id, user_id)


def exists(session_id: str, user_id: str | None = None) -> bool:
    with _CACHE_LOCK:
        if session_id in _CACHE:
            if user_id is None:
                return True
            return db.get_session(session_id, user_id) is not None
    return db.get_session(session_id, user_id) is not None


def reset_for_tests() -> None:
    with _CACHE_LOCK:
        _CACHE.clear()
    db.reset_for_tests()
