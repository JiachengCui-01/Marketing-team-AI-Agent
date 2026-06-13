"""SQLite persistence for sessions, groups, messages, and generated artifacts.

Single-process MVP: one connection per call, WAL mode, foreign keys on.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from marketing_agent.config import PROJECT_ROOT

DB_PATH = PROJECT_ROOT / "tmp" / "marketing_agent.db"
_LOCK = threading.Lock()
_INITIALIZED = False


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


SCHEMA = """
CREATE TABLE IF NOT EXISTS groups (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    group_id TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    FOREIGN KEY (group_id) REFERENCES groups(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at REAL NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, id);

CREATE TABLE IF NOT EXISTS artifacts (
    id TEXT PRIMARY KEY,
    session_id TEXT,
    kind TEXT NOT NULL,
    filename TEXT NOT NULL,
    mime TEXT NOT NULL,
    path TEXT NOT NULL,
    created_at REAL NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_artifacts_session ON artifacts(session_id, created_at);
"""


def init() -> None:
    global _INITIALIZED
    with _LOCK:
        if _INITIALIZED:
            return
        with _connect() as conn:
            conn.executescript(SCHEMA)
        _INITIALIZED = True


def _ensure() -> None:
    if not _INITIALIZED:
        init()


# ---------- groups ----------

def create_group(name: str) -> dict:
    _ensure()
    gid = uuid.uuid4().hex
    now = time.time()
    with _connect() as conn:
        conn.execute(
            "INSERT INTO groups (id, name, created_at) VALUES (?, ?, ?)",
            (gid, name, now),
        )
    return {"id": gid, "name": name, "created_at": now}


def list_groups() -> list[dict]:
    _ensure()
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id, name, created_at FROM groups ORDER BY created_at ASC"
        ).fetchall()
    return [dict(r) for r in rows]


def rename_group(group_id: str, name: str) -> bool:
    _ensure()
    with _connect() as conn:
        cur = conn.execute(
            "UPDATE groups SET name = ? WHERE id = ?", (name, group_id)
        )
        return cur.rowcount > 0


def delete_group(group_id: str) -> bool:
    """Cascade deletes sessions (and via FK, messages/artifacts)."""
    _ensure()
    with _connect() as conn:
        cur = conn.execute("DELETE FROM groups WHERE id = ?", (group_id,))
        return cur.rowcount > 0


# ---------- sessions ----------

def create_session(name: str = "New chat", group_id: str | None = None) -> dict:
    _ensure()
    sid = uuid.uuid4().hex
    now = time.time()
    with _connect() as conn:
        conn.execute(
            "INSERT INTO sessions (id, name, group_id, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            (sid, name, group_id, now, now),
        )
    return {"id": sid, "name": name, "group_id": group_id, "created_at": now, "updated_at": now}


def get_session(session_id: str) -> dict | None:
    _ensure()
    with _connect() as conn:
        row = conn.execute(
            "SELECT id, name, group_id, created_at, updated_at FROM sessions WHERE id = ?",
            (session_id,),
        ).fetchone()
    return dict(row) if row else None


def list_sessions() -> list[dict]:
    _ensure()
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id, name, group_id, created_at, updated_at FROM sessions ORDER BY updated_at DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def update_session(session_id: str, *, name: str | None = None, group_id: str | None = ..., touch: bool = False) -> bool:
    """Update name and/or group_id. Pass group_id=None to set to NULL; omit to leave unchanged."""
    _ensure()
    sets, vals = [], []
    if name is not None:
        sets.append("name = ?")
        vals.append(name)
    if group_id is not ...:
        sets.append("group_id = ?")
        vals.append(group_id)
    if touch or sets:
        sets.append("updated_at = ?")
        vals.append(time.time())
    if not sets:
        return False
    vals.append(session_id)
    with _connect() as conn:
        cur = conn.execute(
            f"UPDATE sessions SET {', '.join(sets)} WHERE id = ?", vals
        )
        return cur.rowcount > 0


def delete_session(session_id: str) -> bool:
    _ensure()
    with _connect() as conn:
        cur = conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        return cur.rowcount > 0


# ---------- messages ----------

def add_message(session_id: str, role: str, content: Any) -> None:
    """content can be str or any JSON-serializable structure (lists for assistant content)."""
    _ensure()
    payload = content if isinstance(content, str) else json.dumps(content, default=str)
    now = time.time()
    with _connect() as conn:
        conn.execute(
            "INSERT INTO messages (session_id, role, content, created_at) VALUES (?, ?, ?, ?)",
            (session_id, role, payload, now),
        )
        conn.execute(
            "UPDATE sessions SET updated_at = ? WHERE id = ?", (now, session_id)
        )


def list_messages(session_id: str) -> list[dict]:
    _ensure()
    with _connect() as conn:
        rows = conn.execute(
            "SELECT role, content, created_at FROM messages WHERE session_id = ? ORDER BY id ASC",
            (session_id,),
        ).fetchall()
    return [dict(r) for r in rows]


# ---------- artifacts ----------

def add_artifact(session_id: str | None, kind: str, filename: str, mime: str, path: str) -> dict:
    _ensure()
    aid = uuid.uuid4().hex
    now = time.time()
    with _connect() as conn:
        conn.execute(
            "INSERT INTO artifacts (id, session_id, kind, filename, mime, path, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (aid, session_id, kind, filename, mime, path, now),
        )
    return {
        "id": aid,
        "session_id": session_id,
        "kind": kind,
        "filename": filename,
        "mime": mime,
        "path": path,
        "created_at": now,
    }


def get_artifact(artifact_id: str) -> dict | None:
    _ensure()
    with _connect() as conn:
        row = conn.execute(
            "SELECT id, session_id, kind, filename, mime, path, created_at FROM artifacts WHERE id = ?",
            (artifact_id,),
        ).fetchone()
    return dict(row) if row else None


def reset_for_tests() -> None:
    global _INITIALIZED
    with _LOCK:
        try:
            DB_PATH.unlink(missing_ok=True)
        except OSError:
            pass
        _INITIALIZED = False
