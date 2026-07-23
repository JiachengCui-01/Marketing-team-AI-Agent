"""SQLite persistence for sessions, groups, messages, and generated artifacts.

Single-process MVP: one connection per call, WAL mode, foreign keys on.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
import uuid
from collections.abc import Iterable
from contextvars import ContextVar
from pathlib import Path
from typing import Any

from marketing_agent.config import PROJECT_ROOT

DB_PATH = Path(os.environ.get("MARKETING_AGENT_DB_PATH", str(PROJECT_ROOT / "tmp" / "marketing_agent.db")))
_LOCK = threading.Lock()
_INITIALIZED = False
CURRENT_USER_ID: ContextVar[str | None] = ContextVar("CURRENT_USER_ID", default=None)


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    account TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    username TEXT NOT NULL,
    real_name TEXT NOT NULL,
    id_card TEXT NOT NULL,
    avatar TEXT,
    phone TEXT,
    email TEXT,
    company TEXT,
    title TEXT,
    bio TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS auth_tokens (
    token TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    expires_at REAL NOT NULL,
    created_at REAL NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_auth_tokens_user ON auth_tokens(user_id, expires_at);

CREATE TABLE IF NOT EXISTS groups (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    name TEXT NOT NULL,
    created_at REAL NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_groups_user ON groups(user_id, created_at);

CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    name TEXT NOT NULL,
    group_id TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (group_id) REFERENCES groups(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id, updated_at);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at REAL NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, id);

CREATE TABLE IF NOT EXISTS session_memory_summaries (
    session_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    summary TEXT NOT NULL,
    source_message_count INTEGER NOT NULL,
    updated_at REAL NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_session_memory_user ON session_memory_summaries(user_id, updated_at);

CREATE TABLE IF NOT EXISTS user_marketing_memory (
    user_id TEXT PRIMARY KEY,
    profile_json TEXT NOT NULL,
    updated_at REAL NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS user_memory_settings (
    user_id TEXT PRIMARY KEY,
    long_term_enabled INTEGER NOT NULL DEFAULT 1,
    updated_at REAL NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS user_marketing_memory_evidence (
    user_id TEXT NOT NULL,
    field TEXT NOT NULL,
    value TEXT NOT NULL,
    count INTEGER NOT NULL,
    explicit INTEGER NOT NULL DEFAULT 0,
    first_seen_at REAL NOT NULL,
    last_seen_at REAL NOT NULL,
    PRIMARY KEY (user_id, field, value),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_user_marketing_memory_evidence_user ON user_marketing_memory_evidence(user_id, last_seen_at);

CREATE TABLE IF NOT EXISTS artifacts (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    session_id TEXT,
    kind TEXT NOT NULL,
    filename TEXT NOT NULL,
    mime TEXT NOT NULL,
    path TEXT NOT NULL,
    created_at REAL NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_artifacts_user ON artifacts(user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_artifacts_session ON artifacts(session_id, created_at);

CREATE TABLE IF NOT EXISTS uploads (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    original_name TEXT NOT NULL,
    mime TEXT NOT NULL,
    ext TEXT NOT NULL,
    size INTEGER NOT NULL,
    path TEXT NOT NULL,
    created_at REAL NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_uploads_user ON uploads(user_id, created_at);

CREATE TABLE IF NOT EXISTS news_configs (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL UNIQUE,
    industry TEXT NOT NULL,
    detail_level TEXT NOT NULL,
    summary_time TEXT NOT NULL,
    timezone TEXT NOT NULL,
    language TEXT NOT NULL DEFAULT 'zh',
    enabled INTEGER NOT NULL DEFAULT 1,
    cancelled_at REAL,
    last_run_at REAL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_news_configs_enabled ON news_configs(enabled);

CREATE TABLE IF NOT EXISTS news_summaries (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    config_id TEXT,
    summary TEXT NOT NULL,
    sources_json TEXT NOT NULL DEFAULT '[]',
    source_score INTEGER NOT NULL DEFAULT 0,
    strong_source_count INTEGER NOT NULL DEFAULT 0,
    weak_source_count INTEGER NOT NULL DEFAULT 0,
    generated_at REAL NOT NULL,
    window_start REAL,
    window_end REAL,
    created_at REAL NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_news_summaries_user ON news_summaries(user_id, created_at);

CREATE TABLE IF NOT EXISTS image_history (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    prompt TEXT NOT NULL,
    style_key TEXT NOT NULL,
    artifact_id TEXT,
    source_upload_id TEXT,
    params TEXT,
    created_at REAL NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (artifact_id) REFERENCES artifacts(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_image_history_user ON image_history(user_id, created_at);

CREATE TABLE IF NOT EXISTS image_templates (
    id TEXT PRIMARY KEY,
    platform TEXT NOT NULL,
    style_key TEXT NOT NULL,
    style TEXT,
    label TEXT NOT NULL,
    prompt TEXT NOT NULL,
    aspect_ratio TEXT,
    sort_order INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_image_templates_platform ON image_templates(platform, style);
"""


def init() -> None:
    global _INITIALIZED
    with _LOCK:
        if _INITIALIZED:
            return
        with _connect() as conn:
            _drop_anonymous_tables_if_needed(conn)
            conn.executescript(SCHEMA)
            _migrate_news_config_language(conn)
            _migrate_news_config_cancelled_at(conn)
            _migrate_news_summary_sources(conn)
            _migrate_image_template_style(conn)
            _migrate_evidence_explicit(conn)
            _seed_image_templates(conn)
        _INITIALIZED = True


def _ensure() -> None:
    if not _INITIALIZED:
        init()


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {str(row["name"]) for row in rows}


def _migrate_news_config_language(conn: sqlite3.Connection) -> None:
    if "language" not in _table_columns(conn, "news_configs"):
        conn.execute(
            "ALTER TABLE news_configs ADD COLUMN language TEXT NOT NULL DEFAULT 'zh'"
        )


def _migrate_news_config_cancelled_at(conn: sqlite3.Connection) -> None:
    if "cancelled_at" not in _table_columns(conn, "news_configs"):
        conn.execute("ALTER TABLE news_configs ADD COLUMN cancelled_at REAL")


def _migrate_news_summary_sources(conn: sqlite3.Connection) -> None:
    cols = _table_columns(conn, "news_summaries")
    if "sources_json" not in cols:
        conn.execute("ALTER TABLE news_summaries ADD COLUMN sources_json TEXT NOT NULL DEFAULT '[]'")
    if "source_score" not in cols:
        conn.execute("ALTER TABLE news_summaries ADD COLUMN source_score INTEGER NOT NULL DEFAULT 0")
    if "strong_source_count" not in cols:
        conn.execute("ALTER TABLE news_summaries ADD COLUMN strong_source_count INTEGER NOT NULL DEFAULT 0")
    if "weak_source_count" not in cols:
        conn.execute("ALTER TABLE news_summaries ADD COLUMN weak_source_count INTEGER NOT NULL DEFAULT 0")


def _migrate_image_template_style(conn: sqlite3.Connection) -> None:
    if "style" not in _table_columns(conn, "image_templates"):
        conn.execute("ALTER TABLE image_templates ADD COLUMN style TEXT")


def _migrate_evidence_explicit(conn: sqlite3.Connection) -> None:
    if "explicit" not in _table_columns(conn, "user_marketing_memory_evidence"):
        conn.execute(
            "ALTER TABLE user_marketing_memory_evidence ADD COLUMN explicit INTEGER NOT NULL DEFAULT 0"
        )


def _drop_anonymous_tables_if_needed(conn: sqlite3.Connection) -> None:
    """The auth release intentionally starts user-owned data from a clean slate."""
    sessions_cols = _table_columns(conn, "sessions")
    if sessions_cols and "user_id" not in sessions_cols:
        conn.executescript(
            """
            DROP TABLE IF EXISTS artifacts;
            DROP TABLE IF EXISTS messages;
            DROP TABLE IF EXISTS sessions;
            DROP TABLE IF EXISTS groups;
            DROP TABLE IF EXISTS uploads;
            """
        )


# ---------- users / auth ----------

def create_user(
    *,
    account: str,
    password_hash: str,
    username: str,
    real_name: str,
    id_card: str,
    avatar: str | None = None,
    phone: str | None = None,
    email: str | None = None,
    company: str | None = None,
    title: str | None = None,
    bio: str | None = None,
) -> dict:
    _ensure()
    uid = uuid.uuid4().hex
    now = time.time()
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO users (
                id, account, password_hash, username, real_name, id_card, avatar,
                phone, email, company, title, bio, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                uid,
                account,
                password_hash,
                username,
                real_name,
                id_card,
                avatar,
                phone,
                email,
                company,
                title,
                bio,
                now,
                now,
            ),
        )
    return get_user(uid) or {}


def get_user(user_id: str) -> dict | None:
    _ensure()
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT id, account, password_hash, username, real_name, id_card, avatar,
                   phone, email, company, title, bio, created_at, updated_at
            FROM users WHERE id = ?
            """,
            (user_id,),
        ).fetchone()
    return dict(row) if row else None


def get_user_by_account(account: str) -> dict | None:
    _ensure()
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT id, account, password_hash, username, real_name, id_card, avatar,
                   phone, email, company, title, bio, created_at, updated_at
            FROM users WHERE account = ?
            """,
            (account,),
        ).fetchone()
    return dict(row) if row else None


def update_user_profile(user_id: str, **fields: str | None) -> dict | None:
    _ensure()
    allowed = {"password_hash", "username", "avatar", "phone", "email", "company", "title", "bio"}
    sets, vals = [], []
    for key, value in fields.items():
        if key in allowed:
            sets.append(f"{key} = ?")
            vals.append(value)
    if not sets:
        return get_user(user_id)
    sets.append("updated_at = ?")
    vals.append(time.time())
    vals.append(user_id)
    with _connect() as conn:
        cur = conn.execute(f"UPDATE users SET {', '.join(sets)} WHERE id = ?", vals)
        if cur.rowcount == 0:
            return None
    return get_user(user_id)


def delete_user(user_id: str) -> bool:
    _ensure()
    with _connect() as conn:
        cur = conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        return cur.rowcount > 0


def create_auth_token(user_id: str, token: str, expires_at: float) -> None:
    _ensure()
    now = time.time()
    with _connect() as conn:
        conn.execute(
            "INSERT INTO auth_tokens (token, user_id, expires_at, created_at) VALUES (?, ?, ?, ?)",
            (token, user_id, expires_at, now),
        )


def get_user_by_token(token: str) -> dict | None:
    _ensure()
    now = time.time()
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT u.id, u.account, u.password_hash, u.username, u.real_name, u.id_card,
                   u.avatar, u.phone, u.email, u.company, u.title, u.bio, u.created_at, u.updated_at
            FROM auth_tokens t
            JOIN users u ON u.id = t.user_id
            WHERE t.token = ? AND t.expires_at > ?
            """,
            (token, now),
        ).fetchone()
    return dict(row) if row else None


def delete_auth_token(token: str) -> bool:
    _ensure()
    with _connect() as conn:
        cur = conn.execute("DELETE FROM auth_tokens WHERE token = ?", (token,))
        return cur.rowcount > 0


# ---------- groups ----------

def create_group(user_id: str, name: str) -> dict:
    _ensure()
    gid = uuid.uuid4().hex
    now = time.time()
    with _connect() as conn:
        conn.execute(
            "INSERT INTO groups (id, user_id, name, created_at) VALUES (?, ?, ?, ?)",
            (gid, user_id, name, now),
        )
    return {"id": gid, "user_id": user_id, "name": name, "created_at": now}


def list_groups(user_id: str) -> list[dict]:
    _ensure()
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id, name, created_at FROM groups WHERE user_id = ? ORDER BY created_at ASC",
            (user_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def rename_group(user_id: str, group_id: str, name: str) -> bool:
    _ensure()
    with _connect() as conn:
        cur = conn.execute(
            "UPDATE groups SET name = ? WHERE id = ? AND user_id = ?", (name, group_id, user_id)
        )
        return cur.rowcount > 0


def delete_group(user_id: str, group_id: str) -> bool:
    """Cascade deletes sessions (and via FK, messages/artifacts)."""
    _ensure()
    with _connect() as conn:
        cur = conn.execute("DELETE FROM groups WHERE id = ? AND user_id = ?", (group_id, user_id))
        return cur.rowcount > 0


# ---------- sessions ----------

def create_session(user_id: str, name: str = "New chat", group_id: str | None = None) -> dict:
    _ensure()
    sid = uuid.uuid4().hex
    now = time.time()
    with _connect() as conn:
        conn.execute(
            "INSERT INTO sessions (id, user_id, name, group_id, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (sid, user_id, name, group_id, now, now),
        )
    return {"id": sid, "user_id": user_id, "name": name, "group_id": group_id, "created_at": now, "updated_at": now}


def get_session(session_id: str, user_id: str | None = None) -> dict | None:
    _ensure()
    with _connect() as conn:
        if user_id is None:
            row = conn.execute(
                "SELECT id, user_id, name, group_id, created_at, updated_at FROM sessions WHERE id = ?",
                (session_id,),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT id, user_id, name, group_id, created_at, updated_at FROM sessions WHERE id = ? AND user_id = ?",
                (session_id, user_id),
            ).fetchone()
    return dict(row) if row else None


def list_sessions(user_id: str) -> list[dict]:
    _ensure()
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id, name, group_id, created_at, updated_at FROM sessions WHERE user_id = ? ORDER BY updated_at DESC",
            (user_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def update_session(session_id: str, *, user_id: str | None = None, name: str | None = None, group_id: str | None = ..., touch: bool = False) -> bool:
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
    where = "id = ?"
    if user_id is not None:
        where += " AND user_id = ?"
        vals.append(user_id)
    with _connect() as conn:
        cur = conn.execute(
            f"UPDATE sessions SET {', '.join(sets)} WHERE {where}", vals
        )
        return cur.rowcount > 0


def delete_session(session_id: str, user_id: str | None = None) -> bool:
    _ensure()
    with _connect() as conn:
        if user_id is None:
            cur = conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        else:
            cur = conn.execute("DELETE FROM sessions WHERE id = ? AND user_id = ?", (session_id, user_id))
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
            "SELECT id, role, content, created_at FROM messages WHERE session_id = ? ORDER BY id ASC",
            (session_id,),
        ).fetchall()
    return [dict(r) for r in rows]


# ---------- memory ----------

def get_session_memory_summary(session_id: str, user_id: str) -> dict | None:
    _ensure()
    with _connect() as conn:
        row = conn.execute(
            "SELECT session_id, user_id, summary, source_message_count, updated_at "
            "FROM session_memory_summaries WHERE session_id = ? AND user_id = ?",
            (session_id, user_id),
        ).fetchone()
    return dict(row) if row else None


def upsert_session_memory_summary(
    session_id: str,
    user_id: str,
    summary: str,
    source_message_count: int,
) -> dict:
    _ensure()
    now = time.time()
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO session_memory_summaries
                (session_id, user_id, summary, source_message_count, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET
                summary = excluded.summary,
                source_message_count = excluded.source_message_count,
                updated_at = excluded.updated_at
            """,
            (session_id, user_id, summary, source_message_count, now),
        )
    return {
        "session_id": session_id,
        "user_id": user_id,
        "summary": summary,
        "source_message_count": source_message_count,
        "updated_at": now,
    }


MARKETING_PROFILE_SCHEMA_VERSION = 1


def get_user_marketing_memory(user_id: str) -> dict | None:
    _ensure()
    with _connect() as conn:
        row = conn.execute(
            "SELECT user_id, profile_json, updated_at FROM user_marketing_memory WHERE user_id = ?",
            (user_id,),
        ).fetchone()
    if row is None:
        return None
    data = dict(row)
    try:
        raw = json.loads(data.get("profile_json") or "{}")
    except (ValueError, TypeError):
        raw = {}
    if not isinstance(raw, dict):
        raw = {}
    # Older rows predate schema versioning — treat a missing marker as v1.
    data["schema_version"] = int(raw.pop("schema_version", 1) or 1)
    data["profile"] = raw
    return data


def upsert_user_marketing_memory(user_id: str, profile: dict) -> dict:
    _ensure()
    now = time.time()
    stored = {**(profile or {}), "schema_version": MARKETING_PROFILE_SCHEMA_VERSION}
    payload = json.dumps(stored, ensure_ascii=False, sort_keys=True)
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO user_marketing_memory (user_id, profile_json, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                profile_json = excluded.profile_json,
                updated_at = excluded.updated_at
            """,
            (user_id, payload, now),
        )
    return {"user_id": user_id, "profile": profile, "profile_json": payload, "updated_at": now}


def delete_user_marketing_memory(user_id: str) -> bool:
    _ensure()
    with _connect() as conn:
        cur = conn.execute("DELETE FROM user_marketing_memory WHERE user_id = ?", (user_id,))
        return cur.rowcount > 0


def delete_user_marketing_memory_evidence(user_id: str) -> int:
    _ensure()
    with _connect() as conn:
        cur = conn.execute(
            "DELETE FROM user_marketing_memory_evidence WHERE user_id = ?", (user_id,)
        )
        return cur.rowcount


def get_user_memory_settings(user_id: str) -> dict:
    _ensure()
    with _connect() as conn:
        row = conn.execute(
            "SELECT user_id, long_term_enabled, updated_at FROM user_memory_settings WHERE user_id = ?",
            (user_id,),
        ).fetchone()
    if row is None:
        return {"user_id": user_id, "long_term_enabled": True, "updated_at": None}
    data = dict(row)
    data["long_term_enabled"] = bool(data.get("long_term_enabled"))
    return data


def set_user_memory_enabled(user_id: str, enabled: bool) -> dict:
    _ensure()
    now = time.time()
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO user_memory_settings (user_id, long_term_enabled, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                long_term_enabled = excluded.long_term_enabled,
                updated_at = excluded.updated_at
            """,
            (user_id, 1 if enabled else 0, now),
        )
    return {"user_id": user_id, "long_term_enabled": enabled, "updated_at": now}


def list_user_marketing_memory_evidence(user_id: str) -> list[dict]:
    _ensure()
    with _connect() as conn:
        rows = conn.execute(
            "SELECT user_id, field, value, count, explicit, first_seen_at, last_seen_at "
            "FROM user_marketing_memory_evidence WHERE user_id = ? ORDER BY field ASC, count DESC, last_seen_at DESC",
            (user_id,),
        ).fetchall()
    out: list[dict] = []
    for row in rows:
        data = dict(row)
        data["explicit"] = bool(data.get("explicit"))
        out.append(data)
    return out


def add_user_marketing_memory_evidence(
    user_id: str, observations: Iterable[tuple[str, str, bool]]
) -> list[dict]:
    """Record profile observations as evidence.

    ``observations`` is an iterable of ``(field, value, explicit)`` triples.
    ``explicit`` marks a direct self-declaration (e.g. "our product is X"),
    which callers may promote at a lower threshold. Repeated observations
    increment the count and can only raise ``explicit`` (never lower it).
    """
    _ensure()
    now = time.time()
    with _connect() as conn:
        for field, raw, explicit in observations:
            value = str(raw).strip()
            if not field or not value:
                continue
            conn.execute(
                """
                INSERT INTO user_marketing_memory_evidence
                    (user_id, field, value, count, explicit, first_seen_at, last_seen_at)
                VALUES (?, ?, ?, 1, ?, ?, ?)
                ON CONFLICT(user_id, field, value) DO UPDATE SET
                    count = count + 1,
                    explicit = MAX(explicit, excluded.explicit),
                    last_seen_at = excluded.last_seen_at
                """,
                (user_id, str(field), value, 1 if explicit else 0, now, now),
            )
    return list_user_marketing_memory_evidence(user_id)


def prune_user_marketing_memory_evidence(
    user_id: str,
    *,
    max_age_days: float = 90.0,
    max_rows_per_field: int = 40,
    min_count: int = 3,
) -> int:
    """Bound the evidence ledger so it cannot grow without limit.

    Drops weak, non-explicit, stale rows (below ``min_count`` and older than
    ``max_age_days``), then caps each field to its ``max_rows_per_field``
    strongest/most-recent rows. Returns the number of rows deleted.
    """
    _ensure()
    cutoff = time.time() - max_age_days * 86400
    deleted = 0
    with _connect() as conn:
        cur = conn.execute(
            "DELETE FROM user_marketing_memory_evidence "
            "WHERE user_id = ? AND explicit = 0 AND count < ? AND last_seen_at < ?",
            (user_id, min_count, cutoff),
        )
        deleted += cur.rowcount or 0
        rows = conn.execute(
            "SELECT field, value FROM user_marketing_memory_evidence WHERE user_id = ? "
            "ORDER BY field ASC, count DESC, last_seen_at DESC",
            (user_id,),
        ).fetchall()
        per_field: dict[str, int] = {}
        overflow: list[tuple[str, str]] = []
        for row in rows:
            field = str(row["field"])
            per_field[field] = per_field.get(field, 0) + 1
            if per_field[field] > max_rows_per_field:
                overflow.append((field, str(row["value"])))
        for field, value in overflow:
            cur = conn.execute(
                "DELETE FROM user_marketing_memory_evidence WHERE user_id = ? AND field = ? AND value = ?",
                (user_id, field, value),
            )
            deleted += cur.rowcount or 0
    return deleted


# ---------- artifacts ----------

def add_artifact(
    session_id: str | None,
    kind: str,
    filename: str,
    mime: str,
    path: str,
    user_id: str | None = None,
) -> dict:
    _ensure()
    owner_id = user_id or CURRENT_USER_ID.get()
    if not owner_id:
        raise ValueError("user_id is required to create an artifact")
    aid = uuid.uuid4().hex
    now = time.time()
    with _connect() as conn:
        conn.execute(
            "INSERT INTO artifacts (id, user_id, session_id, kind, filename, mime, path, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (aid, owner_id, session_id, kind, filename, mime, path, now),
        )
    return {
        "id": aid,
        "user_id": owner_id,
        "session_id": session_id,
        "kind": kind,
        "filename": filename,
        "mime": mime,
        "path": path,
        "created_at": now,
    }


def get_artifact(artifact_id: str, user_id: str | None = None) -> dict | None:
    _ensure()
    with _connect() as conn:
        if user_id is None:
            row = conn.execute(
                "SELECT id, user_id, session_id, kind, filename, mime, path, created_at FROM artifacts WHERE id = ?",
                (artifact_id,),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT id, user_id, session_id, kind, filename, mime, path, created_at FROM artifacts WHERE id = ? AND user_id = ?",
                (artifact_id, user_id),
            ).fetchone()
    return dict(row) if row else None


def list_artifacts(session_id: str, user_id: str | None = None) -> list[dict]:
    _ensure()
    with _connect() as conn:
        if user_id is None:
            rows = conn.execute(
                "SELECT id, user_id, session_id, kind, filename, mime, path, created_at "
                "FROM artifacts WHERE session_id = ? ORDER BY created_at ASC",
                (session_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, user_id, session_id, kind, filename, mime, path, created_at "
                "FROM artifacts WHERE session_id = ? AND user_id = ? ORDER BY created_at ASC",
                (session_id, user_id),
            ).fetchall()
    return [dict(r) for r in rows]


def get_group(user_id: str, group_id: str) -> dict | None:
    _ensure()
    with _connect() as conn:
        row = conn.execute(
            "SELECT id, user_id, name, created_at FROM groups WHERE id = ? AND user_id = ?",
            (group_id, user_id),
        ).fetchone()
    return dict(row) if row else None


# ---------- uploads ----------

def add_upload(user_id: str, file_id: str, original_name: str, mime: str, ext: str, size: int, path: str) -> dict:
    _ensure()
    now = time.time()
    with _connect() as conn:
        conn.execute(
            "INSERT INTO uploads (id, user_id, original_name, mime, ext, size, path, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (file_id, user_id, original_name, mime, ext, size, path, now),
        )
    return {
        "id": file_id,
        "user_id": user_id,
        "original_name": original_name,
        "mime": mime,
        "ext": ext,
        "size": size,
        "path": path,
        "created_at": now,
    }


def get_upload(file_id: str, user_id: str) -> dict | None:
    _ensure()
    with _connect() as conn:
        row = conn.execute(
            "SELECT id, user_id, original_name, mime, ext, size, path, created_at FROM uploads WHERE id = ? AND user_id = ?",
            (file_id, user_id),
        ).fetchone()
    return dict(row) if row else None


# ---------- news ----------

def get_news_config(user_id: str) -> dict | None:
    _ensure()
    with _connect() as conn:
        row = conn.execute(
            "SELECT id, user_id, industry, detail_level, summary_time, timezone, language, enabled, "
            "cancelled_at, last_run_at, created_at, updated_at FROM news_configs WHERE user_id = ?",
            (user_id,),
        ).fetchone()
    if row is None:
        return None
    data = dict(row)
    data["enabled"] = bool(data["enabled"])
    return data


def upsert_news_config(
    user_id: str,
    *,
    industry: str,
    detail_level: str,
    summary_time: str,
    timezone: str,
    language: str = "zh",
    enabled: bool = True,
) -> dict:
    """Create or update the single news config for a user."""
    _ensure()
    now = time.time()
    existing = get_news_config(user_id)
    with _connect() as conn:
        if existing is None:
            cid = uuid.uuid4().hex
            conn.execute(
                "INSERT INTO news_configs (id, user_id, industry, detail_level, summary_time, "
                "timezone, language, enabled, cancelled_at, last_run_at, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?, ?)",
                (cid, user_id, industry, detail_level, summary_time, timezone, language, int(enabled), now, now),
            )
        else:
            # Saving a config (re)activates the task: clear any cancellation marker.
            conn.execute(
                "UPDATE news_configs SET industry = ?, detail_level = ?, summary_time = ?, "
                "timezone = ?, language = ?, enabled = ?, cancelled_at = NULL, updated_at = ? "
                "WHERE user_id = ?",
                (industry, detail_level, summary_time, timezone, language, int(enabled), now, user_id),
            )
    return get_news_config(user_id)  # type: ignore[return-value]


def delete_news_config(user_id: str) -> bool:
    _ensure()
    with _connect() as conn:
        cur = conn.execute("DELETE FROM news_configs WHERE user_id = ?", (user_id,))
        return cur.rowcount > 0


def delete_news_data(user_id: str) -> None:
    """Wipe both the news config and all stored summaries for a user.

    Used when a cancelled task reaches its revert time — the panel returns to the
    pre-activation empty state.
    """
    _ensure()
    with _connect() as conn:
        conn.execute("DELETE FROM news_summaries WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM news_configs WHERE user_id = ?", (user_id,))


def cancel_news_config(user_id: str, ts: float) -> dict | None:
    """Soft-cancel: stop the scheduler for this config and stamp the cancel time.

    The row is kept (enabled=0, cancelled_at=ts) so the panel can keep showing the
    last summary until the revert time, after which it is fully deleted.
    """
    _ensure()
    with _connect() as conn:
        cur = conn.execute(
            "UPDATE news_configs SET enabled = 0, cancelled_at = ?, updated_at = ? WHERE user_id = ?",
            (ts, time.time(), user_id),
        )
        if cur.rowcount == 0:
            return None
    return get_news_config(user_id)


def set_news_config_last_run(user_id: str, ts: float) -> None:
    _ensure()
    with _connect() as conn:
        conn.execute(
            "UPDATE news_configs SET last_run_at = ? WHERE user_id = ?", (ts, user_id)
        )


def set_news_config_language(user_id: str, language: str) -> None:
    _ensure()
    with _connect() as conn:
        conn.execute(
            "UPDATE news_configs SET language = ?, updated_at = ? WHERE user_id = ?",
            (language, time.time(), user_id),
        )


def list_enabled_news_configs() -> list[dict]:
    _ensure()
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id, user_id, industry, detail_level, summary_time, timezone, language, enabled, "
            "cancelled_at, last_run_at, created_at, updated_at FROM news_configs WHERE enabled = 1"
        ).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d["enabled"] = bool(d["enabled"])
        result.append(d)
    return result


def list_cancelled_news_configs() -> list[dict]:
    """Configs that were soft-cancelled and are awaiting their revert-time cleanup."""
    _ensure()
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id, user_id, industry, detail_level, summary_time, timezone, language, enabled, "
            "cancelled_at, last_run_at, created_at, updated_at FROM news_configs "
            "WHERE enabled = 0 AND cancelled_at IS NOT NULL"
        ).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d["enabled"] = bool(d["enabled"])
        result.append(d)
    return result


def add_news_summary(
    user_id: str,
    config_id: str | None,
    summary: str,
    generated_at: float,
    window_start: float | None,
    window_end: float | None,
    sources: list[dict] | None = None,
    source_score: int = 0,
    strong_source_count: int = 0,
    weak_source_count: int = 0,
) -> dict:
    _ensure()
    sid = uuid.uuid4().hex
    now = time.time()
    sources_json = json.dumps(sources or [], ensure_ascii=False)
    with _connect() as conn:
        conn.execute(
            "INSERT INTO news_summaries (id, user_id, config_id, summary, sources_json, "
            "source_score, strong_source_count, weak_source_count, generated_at, "
            "window_start, window_end, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                sid,
                user_id,
                config_id,
                summary,
                sources_json,
                source_score,
                strong_source_count,
                weak_source_count,
                generated_at,
                window_start,
                window_end,
                now,
            ),
        )
    return {
        "id": sid,
        "user_id": user_id,
        "config_id": config_id,
        "summary": summary,
        "sources": sources or [],
        "source_score": source_score,
        "strong_source_count": strong_source_count,
        "weak_source_count": weak_source_count,
        "generated_at": generated_at,
        "window_start": window_start,
        "window_end": window_end,
        "created_at": now,
    }


def get_latest_news_summary(user_id: str) -> dict | None:
    _ensure()
    with _connect() as conn:
        row = conn.execute(
            "SELECT id, user_id, config_id, summary, sources_json, source_score, "
            "strong_source_count, weak_source_count, generated_at, window_start, window_end, "
            "created_at FROM news_summaries WHERE user_id = ? ORDER BY created_at DESC LIMIT 1",
            (user_id,),
        ).fetchone()
    if row is None:
        return None
    data = dict(row)
    try:
        data["sources"] = json.loads(data.pop("sources_json") or "[]")
    except (ValueError, TypeError):
        data["sources"] = []
    return data


# ---------- image generation ----------

# Global, editorial template catalog (not per-user). ``platform`` is the marketplace/
# channel, ``style`` is the visual look, and ``style_key`` is the generation skill key
# (see marketing_agent.agents.image_skills). Reseeded deterministically on init.
# Columns: (id, platform, style_key, style, label, prompt, aspect_ratio, sort_order)
_IMAGE_TEMPLATE_SEED = [
    ("tpl_taobao_white", "taobao", "taobao", "white", "纯白主图",
     "Clean e-commerce main image on a pure white background, product centered and sharp.", "1:1", 10),
    ("tpl_taobao_scene", "taobao", "taobao", "scene", "场景主图",
     "Product hero shot in a minimal lifestyle scene with soft shadows.", "1:1", 20),
    ("tpl_taobao_promo", "taobao", "taobao", "promo", "促销氛围图",
     "High-energy promotional main image with bold accent color blocks and space for a price tag.", "1:1", 30),
    ("tpl_xhs_lifestyle", "xiaohongshu", "xiaohongshu", "lifestyle", "生活场景",
     "Warm lifestyle flat-lay with cozy props and space for a caption sticker at the top.", "3:4", 10),
    ("tpl_xhs_hand", "xiaohongshu", "xiaohongshu", "handheld", "手持展示",
     "Aspirational hand-held product shot with soft natural light.", "3:4", 20),
    ("tpl_xhs_flatlay", "xiaohongshu", "xiaohongshu", "flatlay", "平铺构图",
     "Top-down flat-lay with coordinated props arranged around the product.", "3:4", 30),
    ("tpl_amazon_white", "amazon", "amazon", "white", "合规白底主图",
     "Marketplace-compliant main image: product only on pure white, straight-on hero angle.", "1:1", 10),
    ("tpl_amazon_multi", "amazon", "amazon", "multiangle", "多角度展示",
     "Product shown from multiple angles on white, arranged cleanly for a listing gallery.", "1:1", 20),
    ("tpl_ins_editorial", "instagram", "instagram", "editorial", "杂志风",
     "Editorial feed image with a cohesive color palette and shallow depth of field.", "4:5", 10),
    ("tpl_ins_minimal", "instagram", "instagram", "minimal", "极简风",
     "Minimalist composition with lots of negative space and one confident focal point.", "4:5", 20),
    ("tpl_generic_clean", "generic", "generic", "clean", "干净背景",
     "Versatile marketing composition on a simple neutral background.", "1:1", 10),
]


def _seed_image_templates(conn: sqlite3.Connection) -> None:
    # Global catalog: replace wholesale so edits to the seed take effect on restart.
    conn.execute("DELETE FROM image_templates")
    for tid, platform, style_key, style, label, prompt, ratio, order in _IMAGE_TEMPLATE_SEED:
        conn.execute(
            "INSERT INTO image_templates "
            "(id, platform, style_key, style, label, prompt, aspect_ratio, sort_order) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (tid, platform, style_key, style, label, prompt, ratio, order),
        )


def add_image_history(
    user_id: str,
    prompt: str,
    style_key: str,
    artifact_id: str | None,
    source_upload_id: str | None,
    params: dict | None = None,
) -> dict:
    _ensure()
    hid = uuid.uuid4().hex
    now = time.time()
    params_json = json.dumps(params or {})
    with _connect() as conn:
        conn.execute(
            "INSERT INTO image_history (id, user_id, prompt, style_key, artifact_id, "
            "source_upload_id, params, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (hid, user_id, prompt, style_key, artifact_id, source_upload_id, params_json, now),
        )
    return {
        "id": hid,
        "user_id": user_id,
        "prompt": prompt,
        "style_key": style_key,
        "artifact_id": artifact_id,
        "source_upload_id": source_upload_id,
        "params": params or {},
        "created_at": now,
    }


def _row_to_history(row: sqlite3.Row) -> dict:
    data = dict(row)
    try:
        data["params"] = json.loads(data.get("params") or "{}")
    except (ValueError, TypeError):
        data["params"] = {}
    return data


def list_image_history(user_id: str, limit: int = 50) -> list[dict]:
    _ensure()
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id, user_id, prompt, style_key, artifact_id, source_upload_id, params, created_at "
            "FROM image_history WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()
    return [_row_to_history(r) for r in rows]


def get_image_history(history_id: str, user_id: str) -> dict | None:
    _ensure()
    with _connect() as conn:
        row = conn.execute(
            "SELECT id, user_id, prompt, style_key, artifact_id, source_upload_id, params, created_at "
            "FROM image_history WHERE id = ? AND user_id = ?",
            (history_id, user_id),
        ).fetchone()
    return _row_to_history(row) if row else None


def delete_image_history(history_id: str, user_id: str) -> bool:
    _ensure()
    with _connect() as conn:
        cur = conn.execute(
            "DELETE FROM image_history WHERE id = ? AND user_id = ?",
            (history_id, user_id),
        )
        return cur.rowcount > 0


def list_image_templates(platform: str | None = None, style: str | None = None) -> list[dict]:
    _ensure()
    clauses = []
    params: list = []
    if platform and platform != "all":
        clauses.append("platform = ?")
        params.append(platform)
    if style and style != "all":
        clauses.append("style = ?")
        params.append(style)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id, platform, style_key, style, label, prompt, aspect_ratio, sort_order "
            f"FROM image_templates{where} ORDER BY platform ASC, sort_order ASC, label ASC",
            params,
        ).fetchall()
    return [dict(r) for r in rows]


def get_image_template(template_id: str) -> dict | None:
    _ensure()
    with _connect() as conn:
        row = conn.execute(
            "SELECT id, platform, style_key, style, label, prompt, aspect_ratio, sort_order "
            "FROM image_templates WHERE id = ?",
            (template_id,),
        ).fetchone()
    return dict(row) if row else None


def reset_for_tests() -> None:
    global _INITIALIZED
    with _LOCK:
        try:
            for path in (DB_PATH, DB_PATH.with_suffix(DB_PATH.suffix + "-wal"), DB_PATH.with_suffix(DB_PATH.suffix + "-shm")):
                path.unlink(missing_ok=True)
        except OSError:
            try:
                with _connect() as conn:
                    conn.executescript(
                        """
                        DROP TABLE IF EXISTS auth_tokens;
                        DROP TABLE IF EXISTS image_history;
                        DROP TABLE IF EXISTS image_templates;
                        DROP TABLE IF EXISTS news_summaries;
                        DROP TABLE IF EXISTS news_configs;
                        DROP TABLE IF EXISTS uploads;
                        DROP TABLE IF EXISTS artifacts;
                        DROP TABLE IF EXISTS user_marketing_memory_evidence;
                        DROP TABLE IF EXISTS user_marketing_memory;
                        DROP TABLE IF EXISTS user_memory_settings;
                        DROP TABLE IF EXISTS session_memory_summaries;
                        DROP TABLE IF EXISTS messages;
                        DROP TABLE IF EXISTS sessions;
                        DROP TABLE IF EXISTS groups;
                        DROP TABLE IF EXISTS users;
                        """
                    )
            except OSError:
                pass
        _INITIALIZED = False
