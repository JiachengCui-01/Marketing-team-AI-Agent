"""SQLite persistence for sessions, groups, messages, and generated artifacts.

Single-process MVP: one connection per call, WAL mode, foreign keys on.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
import time
import unicodedata
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

-- enterprise collaboration: organizations + directory
CREATE TABLE IF NOT EXISTS organizations (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    owner_id TEXT NOT NULL,
    invite_code TEXT NOT NULL UNIQUE,
    created_at REAL NOT NULL,
    FOREIGN KEY (owner_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS org_members (
    org_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'member',
    joined_at REAL NOT NULL,
    PRIMARY KEY (org_id, user_id),
    FOREIGN KEY (org_id) REFERENCES organizations(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_org_members_user ON org_members(user_id, joined_at);

CREATE TABLE IF NOT EXISTS external_contacts (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    contact_user_id TEXT,
    name TEXT NOT NULL,
    phone TEXT,
    email TEXT,
    company TEXT,
    title TEXT,
    avatar TEXT,
    starred INTEGER NOT NULL DEFAULT 0,
    source TEXT NOT NULL DEFAULT 'manual',
    created_at REAL NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (contact_user_id) REFERENCES users(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_external_contacts_user ON external_contacts(user_id, created_at);

CREATE TABLE IF NOT EXISTS contact_requests (
    id TEXT PRIMARY KEY,
    from_user_id TEXT NOT NULL,
    to_user_id TEXT NOT NULL,
    message TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at REAL NOT NULL,
    responded_at REAL,
    FOREIGN KEY (from_user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (to_user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_contact_requests_to ON contact_requests(to_user_id, status);
CREATE INDEX IF NOT EXISTS idx_contact_requests_from ON contact_requests(from_user_id, status);

CREATE TABLE IF NOT EXISTS contact_stars (
    user_id TEXT NOT NULL,
    member_user_id TEXT NOT NULL,
    created_at REAL NOT NULL,
    PRIMARY KEY (user_id, member_user_id),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (member_user_id) REFERENCES users(id) ON DELETE CASCADE
);

-- enterprise collaboration: instant messaging (direct + group)
CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    title TEXT,
    org_id TEXT,
    created_by TEXT NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_conversations_updated ON conversations(updated_at);

CREATE TABLE IF NOT EXISTS conversation_members (
    conversation_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'member',
    last_read_at REAL NOT NULL DEFAULT 0,
    joined_at REAL NOT NULL,
    PRIMARY KEY (conversation_id, user_id),
    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_conversation_members_user ON conversation_members(user_id);

CREATE TABLE IF NOT EXISTS im_messages (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    sender_id TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'text',
    content TEXT NOT NULL,
    created_at REAL NOT NULL,
    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE,
    FOREIGN KEY (sender_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_im_messages_conv ON im_messages(conversation_id, created_at);

-- AI OA: approvals / tasks / calendar / knowledge base
CREATE TABLE IF NOT EXISTS approvals (
    id TEXT PRIMARY KEY,
    org_id TEXT,
    applicant_id TEXT NOT NULL,
    type TEXT NOT NULL,
    title TEXT NOT NULL,
    form_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'pending',
    current_step INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    FOREIGN KEY (applicant_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_approvals_applicant ON approvals(applicant_id, created_at);
CREATE INDEX IF NOT EXISTS idx_approvals_status ON approvals(status, created_at);

CREATE TABLE IF NOT EXISTS approval_steps (
    approval_id TEXT NOT NULL,
    step_index INTEGER NOT NULL,
    approver_id TEXT NOT NULL,
    action TEXT NOT NULL DEFAULT 'pending',
    comment TEXT,
    acted_at REAL,
    PRIMARY KEY (approval_id, step_index),
    FOREIGN KEY (approval_id) REFERENCES approvals(id) ON DELETE CASCADE,
    FOREIGN KEY (approver_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_approval_steps_approver ON approval_steps(approver_id, action);

CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    org_id TEXT,
    creator_id TEXT NOT NULL,
    assignee_id TEXT,
    title TEXT NOT NULL,
    detail TEXT,
    due_at REAL,
    priority TEXT NOT NULL DEFAULT 'normal',
    status TEXT NOT NULL DEFAULT 'open',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    FOREIGN KEY (creator_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (assignee_id) REFERENCES users(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_tasks_assignee ON tasks(assignee_id, status);
CREATE INDEX IF NOT EXISTS idx_tasks_creator ON tasks(creator_id, created_at);

CREATE TABLE IF NOT EXISTS calendar_events (
    id TEXT PRIMARY KEY,
    org_id TEXT,
    owner_id TEXT NOT NULL,
    title TEXT NOT NULL,
    start_at REAL NOT NULL,
    end_at REAL,
    location TEXT,
    attendees_json TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'active',
    created_at REAL NOT NULL,
    FOREIGN KEY (owner_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_calendar_owner ON calendar_events(owner_id, start_at);

CREATE TABLE IF NOT EXISTS kb_documents (
    id TEXT PRIMARY KEY,
    org_id TEXT,
    uploader_id TEXT NOT NULL,
    title TEXT NOT NULL,
    text_content TEXT NOT NULL DEFAULT '',
    source_upload_id TEXT,
    source_artifact_id TEXT,
    scope TEXT NOT NULL DEFAULT 'org',
    created_at REAL NOT NULL,
    FOREIGN KEY (uploader_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_kb_documents_org ON kb_documents(org_id, created_at);

CREATE TABLE IF NOT EXISTS kb_chunks (
    doc_id TEXT NOT NULL,
    chunk_index INTEGER NOT NULL,
    text TEXT NOT NULL,
    embedding_json TEXT,
    PRIMARY KEY (doc_id, chunk_index),
    FOREIGN KEY (doc_id) REFERENCES kb_documents(id) ON DELETE CASCADE
);
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
            _migrate_kb_scope(conn)
            _migrate_calendar_status(conn)
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


def _migrate_kb_scope(conn: sqlite3.Connection) -> None:
    if "kb_documents" in {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}:
        if "scope" not in _table_columns(conn, "kb_documents"):
            conn.execute("ALTER TABLE kb_documents ADD COLUMN scope TEXT NOT NULL DEFAULT 'org'")


def _migrate_calendar_status(conn: sqlite3.Connection) -> None:
    if "calendar_events" in {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}:
        if "status" not in _table_columns(conn, "calendar_events"):
            conn.execute("ALTER TABLE calendar_events ADD COLUMN status TEXT NOT NULL DEFAULT 'active'")


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


def _norm_evidence_key(value: str) -> str:
    """Normalized key for merging trivially-different phrasings of one value.

    Folds case, full/half-width, whitespace and punctuation so e.g.
    "AI 办公Agent系统" and "ai办公agent系统。" collapse to the same key. Deeper
    paraphrase merging (e.g. "AI办公Agent系统" vs "AI办公Agent") is handled by
    LLM canonicalization at extraction time.
    """
    s = unicodedata.normalize("NFKC", str(value)).casefold().strip()
    return re.sub(r"[\s\W_]+", "", s, flags=re.UNICODE)


def add_user_marketing_memory_evidence(
    user_id: str, observations: Iterable[tuple[str, str, bool]]
) -> list[dict]:
    """Record profile observations as evidence.

    ``observations`` is an iterable of ``(field, value, explicit)`` triples.
    ``explicit`` marks a direct self-declaration. A new value is merged into an
    existing evidence row when it normalizes to the same key (see
    ``_norm_evidence_key``) so near-duplicate phrasings accumulate one count
    instead of fragmenting; the first-seen surface form is kept as the display
    value. Repeated observations increment the count and can only raise
    ``explicit`` (never lower it).
    """
    _ensure()
    now = time.time()
    with _connect() as conn:
        for field, raw, explicit in observations:
            value = str(raw).strip()
            field = str(field)
            if not field or not value:
                continue
            key = _norm_evidence_key(value)
            canonical: str | None = None
            if key:
                for row in conn.execute(
                    "SELECT value FROM user_marketing_memory_evidence WHERE user_id = ? AND field = ?",
                    (user_id, field),
                ).fetchall():
                    if _norm_evidence_key(row["value"]) == key:
                        canonical = str(row["value"])
                        break
            if canonical is not None:
                conn.execute(
                    "UPDATE user_marketing_memory_evidence "
                    "SET count = count + 1, explicit = MAX(explicit, ?), last_seen_at = ? "
                    "WHERE user_id = ? AND field = ? AND value = ?",
                    (1 if explicit else 0, now, user_id, field, canonical),
                )
            else:
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
                    (user_id, field, value, 1 if explicit else 0, now, now),
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


def get_upload_any(file_id: str) -> dict | None:
    """Fetch an upload regardless of owner. Callers MUST authorize access first
    (e.g. verify the file is shared in a conversation the requester belongs to)."""
    _ensure()
    with _connect() as conn:
        row = conn.execute(
            "SELECT id, user_id, original_name, mime, ext, size, path, created_at FROM uploads WHERE id = ?",
            (file_id,),
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


# ---------- organizations / directory ----------

def _gen_invite_code() -> str:
    return uuid.uuid4().hex[:8].upper()


def create_org(owner_id: str, name: str) -> dict:
    _ensure()
    oid = uuid.uuid4().hex
    now = time.time()
    code = _gen_invite_code()
    with _connect() as conn:
        for _ in range(6):
            try:
                conn.execute(
                    "INSERT INTO organizations (id, name, owner_id, invite_code, created_at) VALUES (?, ?, ?, ?, ?)",
                    (oid, name, owner_id, code, now),
                )
                break
            except sqlite3.IntegrityError:
                code = _gen_invite_code()
        else:
            raise RuntimeError("could not allocate a unique invite code")
        conn.execute(
            "INSERT OR IGNORE INTO org_members (org_id, user_id, role, joined_at) VALUES (?, ?, 'owner', ?)",
            (oid, owner_id, now),
        )
    return {"id": oid, "name": name, "owner_id": owner_id, "invite_code": code, "created_at": now}


def get_current_org(user_id: str) -> dict | None:
    """The org the user is currently in — their most recently joined membership."""
    _ensure()
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT o.id, o.name, o.owner_id, o.invite_code, o.created_at, m.role AS my_role
            FROM org_members m
            JOIN organizations o ON o.id = m.org_id
            WHERE m.user_id = ?
            ORDER BY m.joined_at DESC
            LIMIT 1
            """,
            (user_id,),
        ).fetchone()
    return dict(row) if row else None


def get_or_create_default_org(user_id: str, username: str) -> dict:
    org = get_current_org(user_id)
    if org is not None:
        return org
    name = f"{username}'s organization" if username else "My organization"
    create_org(user_id, name)
    org = get_current_org(user_id)
    return org or {}


def join_org_by_invite(user_id: str, invite_code: str) -> dict | None:
    _ensure()
    code = (invite_code or "").strip().upper()
    now = time.time()
    with _connect() as conn:
        org = conn.execute(
            "SELECT id FROM organizations WHERE invite_code = ?", (code,)
        ).fetchone()
        if org is None:
            return None
        conn.execute(
            "INSERT OR IGNORE INTO org_members (org_id, user_id, role, joined_at) VALUES (?, ?, 'member', ?)",
            (org["id"], user_id, now),
        )
        # Bump joined_at so this org becomes the user's current org (even on rejoin).
        conn.execute(
            "UPDATE org_members SET joined_at = ? WHERE org_id = ? AND user_id = ?",
            (now, org["id"], user_id),
        )
    return get_current_org(user_id)


def list_org_members(org_id: str) -> list[dict]:
    _ensure()
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT u.id, u.account, u.username, u.real_name, u.avatar, u.email, u.phone,
                   u.company, u.title, m.role, m.joined_at
            FROM org_members m
            JOIN users u ON u.id = m.user_id
            WHERE m.org_id = ?
            ORDER BY CASE m.role WHEN 'owner' THEN 0 WHEN 'admin' THEN 1 ELSE 2 END, m.joined_at ASC
            """,
            (org_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_org_membership(org_id: str, user_id: str) -> dict | None:
    _ensure()
    with _connect() as conn:
        row = conn.execute(
            "SELECT org_id, user_id, role, joined_at FROM org_members WHERE org_id = ? AND user_id = ?",
            (org_id, user_id),
        ).fetchone()
    return dict(row) if row else None


def add_org_member(org_id: str, user_id: str, role: str = "member") -> None:
    _ensure()
    with _connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO org_members (org_id, user_id, role, joined_at) VALUES (?, ?, ?, ?)",
            (org_id, user_id, role, time.time()),
        )


def remove_org_member(org_id: str, target_user_id: str) -> bool:
    _ensure()
    with _connect() as conn:
        cur = conn.execute(
            "DELETE FROM org_members WHERE org_id = ? AND user_id = ?",
            (org_id, target_user_id),
        )
        return cur.rowcount > 0


# ---------- AI OA: approvals ----------

def _approval_row(conn: sqlite3.Connection, row: sqlite3.Row) -> dict:
    d = dict(row)
    d["form"] = json.loads(d.pop("form_json") or "{}")
    steps = conn.execute(
        "SELECT step_index, approver_id, action, comment, acted_at "
        "FROM approval_steps WHERE approval_id = ? ORDER BY step_index",
        (d["id"],),
    ).fetchall()
    d["steps"] = [dict(s) for s in steps]
    return d


def create_approval(
    applicant_id: str,
    type_: str,
    title: str,
    form: dict,
    approver_ids: Iterable[str],
    org_id: str | None = None,
) -> dict:
    _ensure()
    aid = uuid.uuid4().hex
    now = time.time()
    with _connect() as conn:
        conn.execute(
            "INSERT INTO approvals (id, org_id, applicant_id, type, title, form_json, "
            "status, current_step, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (aid, org_id, applicant_id, type_, title, json.dumps(form, ensure_ascii=False),
             "pending", 0, now, now),
        )
        for idx, approver in enumerate(approver_ids):
            conn.execute(
                "INSERT INTO approval_steps (approval_id, step_index, approver_id, action) "
                "VALUES (?, ?, ?, 'pending')",
                (aid, idx, approver),
            )
        row = conn.execute("SELECT * FROM approvals WHERE id = ?", (aid,)).fetchone()
        return _approval_row(conn, row)


def get_approval(approval_id: str) -> dict | None:
    _ensure()
    with _connect() as conn:
        row = conn.execute("SELECT * FROM approvals WHERE id = ?", (approval_id,)).fetchone()
        return _approval_row(conn, row) if row else None


def list_approvals_created_by(user_id: str) -> list[dict]:
    _ensure()
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM approvals WHERE applicant_id = ? ORDER BY created_at DESC",
            (user_id,),
        ).fetchall()
        return [_approval_row(conn, r) for r in rows]


def list_approvals_pending_for(user_id: str) -> list[dict]:
    """Approvals where it is currently this user's turn to act."""
    _ensure()
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT a.* FROM approvals a
            JOIN approval_steps s ON s.approval_id = a.id AND s.step_index = a.current_step
            WHERE a.status = 'pending' AND s.approver_id = ? AND s.action = 'pending'
            ORDER BY a.created_at DESC
            """,
            (user_id,),
        ).fetchall()
        return [_approval_row(conn, r) for r in rows]


def list_approvals_acted_by(user_id: str) -> list[dict]:
    _ensure()
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT DISTINCT a.* FROM approvals a
            JOIN approval_steps s ON s.approval_id = a.id
            WHERE s.approver_id = ? AND s.action != 'pending'
            ORDER BY a.updated_at DESC
            """,
            (user_id,),
        ).fetchall()
        return [_approval_row(conn, r) for r in rows]


def act_on_approval(
    approval_id: str, approver_id: str, action: str, comment: str | None = None
) -> dict | None:
    """Record an approver's decision and advance the workflow.

    ``action`` is ``'approved'`` or ``'rejected'``. Returns the updated approval,
    or ``None`` if the caller is not the current approver / it is already settled.
    """
    _ensure()
    now = time.time()
    with _connect() as conn:
        appr = conn.execute("SELECT * FROM approvals WHERE id = ?", (approval_id,)).fetchone()
        if appr is None or appr["status"] != "pending":
            return None
        step = conn.execute(
            "SELECT * FROM approval_steps WHERE approval_id = ? AND step_index = ?",
            (approval_id, appr["current_step"]),
        ).fetchone()
        if step is None or step["approver_id"] != approver_id or step["action"] != "pending":
            return None
        conn.execute(
            "UPDATE approval_steps SET action = ?, comment = ?, acted_at = ? "
            "WHERE approval_id = ? AND step_index = ?",
            (action, comment, now, approval_id, appr["current_step"]),
        )
        if action == "rejected":
            conn.execute(
                "UPDATE approvals SET status = 'rejected', updated_at = ? WHERE id = ?",
                (now, approval_id),
            )
        else:
            total = conn.execute(
                "SELECT COUNT(*) AS c FROM approval_steps WHERE approval_id = ?", (approval_id,)
            ).fetchone()["c"]
            next_step = int(appr["current_step"]) + 1
            if next_step >= total:
                conn.execute(
                    "UPDATE approvals SET status = 'approved', updated_at = ? WHERE id = ?",
                    (now, approval_id),
                )
            else:
                conn.execute(
                    "UPDATE approvals SET current_step = ?, updated_at = ? WHERE id = ?",
                    (next_step, now, approval_id),
                )
        row = conn.execute("SELECT * FROM approvals WHERE id = ?", (approval_id,)).fetchone()
        return _approval_row(conn, row)


def update_approval(approval_id: str, applicant_id: str, title=None, form=None) -> dict | None:
    """Modify one's own still-pending application (title/form). Owner-only."""
    _ensure()
    with _connect() as conn:
        appr = conn.execute("SELECT * FROM approvals WHERE id = ?", (approval_id,)).fetchone()
        if appr is None or appr["applicant_id"] != applicant_id or appr["status"] != "pending":
            return None
        sets, args = [], []
        if title is not None:
            sets.append("title = ?")
            args.append(title)
        if form is not None:
            sets.append("form_json = ?")
            args.append(json.dumps(form, ensure_ascii=False))
        if sets:
            sets.append("updated_at = ?")
            args.append(time.time())
            conn.execute(f"UPDATE approvals SET {', '.join(sets)} WHERE id = ?", (*args, approval_id))
        row = conn.execute("SELECT * FROM approvals WHERE id = ?", (approval_id,)).fetchone()
        return _approval_row(conn, row)


def withdraw_approval(approval_id: str, applicant_id: str) -> dict | None:
    """Withdraw one's own still-pending application."""
    _ensure()
    with _connect() as conn:
        appr = conn.execute("SELECT * FROM approvals WHERE id = ?", (approval_id,)).fetchone()
        if appr is None or appr["applicant_id"] != applicant_id or appr["status"] != "pending":
            return None
        conn.execute(
            "UPDATE approvals SET status = 'withdrawn', updated_at = ? WHERE id = ?",
            (time.time(), approval_id),
        )
        row = conn.execute("SELECT * FROM approvals WHERE id = ?", (approval_id,)).fetchone()
        return _approval_row(conn, row)


# ---------- AI OA: tasks ----------

def create_task(
    creator_id: str,
    title: str,
    detail: str | None = None,
    priority: str = "normal",
    due_at: float | None = None,
    assignee_id: str | None = None,
    org_id: str | None = None,
) -> dict:
    _ensure()
    tid = uuid.uuid4().hex
    now = time.time()
    with _connect() as conn:
        conn.execute(
            "INSERT INTO tasks (id, org_id, creator_id, assignee_id, title, detail, due_at, "
            "priority, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'open', ?, ?)",
            (tid, org_id, creator_id, assignee_id, title, detail, due_at, priority, now, now),
        )
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (tid,)).fetchone()
        return dict(row)


def get_task(task_id: str) -> dict | None:
    _ensure()
    with _connect() as conn:
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return dict(row) if row else None


def list_tasks(user_id: str, scope: str = "assigned") -> list[dict]:
    """Tasks are visible only to their creator and assignee.

    scope: 'created' = active tasks I created; 'assigned' = active tasks others assigned
    to me; 'done' = my completed tasks (either role); 'all' = any of mine (any status).
    """
    _ensure()
    with _connect() as conn:
        if scope == "created":
            where = "creator_id = ? AND status != 'done'"
            args: tuple = (user_id,)
        elif scope == "done":
            where = "(creator_id = ? OR assignee_id = ?) AND status = 'done'"
            args = (user_id, user_id)
        elif scope == "all":
            where = "creator_id = ? OR assignee_id = ?"
            args = (user_id, user_id)
        else:  # assigned to me by someone else
            where = "assignee_id = ? AND creator_id != ? AND status != 'done'"
            args = (user_id, user_id)
        rows = conn.execute(
            f"SELECT * FROM tasks WHERE {where} ORDER BY "
            "CASE status WHEN 'open' THEN 0 WHEN 'awaiting_confirmation' THEN 1 ELSE 2 END, "
            "COALESCE(due_at, 9e18) ASC, created_at DESC",
            args,
        ).fetchall()
        return [dict(r) for r in rows]


def _is_self_task(row) -> bool:
    return row["assignee_id"] is None or row["assignee_id"] == row["creator_id"]


def update_task_status(task_id: str, user_id: str, status: str) -> dict | None:
    """Progress a task's status with the assignment rules:

    - reopen ('open') by creator or assignee;
    - complete ('done') on a self task → done immediately;
    - complete on an assigned task by the assignee → 'awaiting_confirmation'
      (the creator must confirm before it counts as done).
    """
    _ensure()
    now = time.time()
    with _connect() as conn:
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if row is None or user_id not in (row["creator_id"], row["assignee_id"]):
            return None
        if status == "open":
            new_status = "open"
        elif status == "done":
            if _is_self_task(row):
                new_status = "done"
            elif user_id == row["assignee_id"]:
                new_status = "awaiting_confirmation"
            else:
                return None  # creator can't self-complete an assigned task; must confirm
        else:
            return None
        conn.execute(
            "UPDATE tasks SET status = ?, updated_at = ? WHERE id = ?", (new_status, now, task_id)
        )
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return dict(row)


def confirm_task(task_id: str, creator_id: str) -> dict | None:
    """The creator confirms an assignee-completed task, moving it to 'done' for both."""
    _ensure()
    with _connect() as conn:
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if row is None or row["creator_id"] != creator_id or row["status"] != "awaiting_confirmation":
            return None
        conn.execute(
            "UPDATE tasks SET status = 'done', updated_at = ? WHERE id = ?", (time.time(), task_id)
        )
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return dict(row)


def clear_done_tasks(user_id: str) -> int:
    """Clear the caller's completed tasks (either role)."""
    _ensure()
    with _connect() as conn:
        cur = conn.execute(
            "DELETE FROM tasks WHERE (creator_id = ? OR assignee_id = ?) AND status = 'done'",
            (user_id, user_id),
        )
        return cur.rowcount


def delete_task(task_id: str, user_id: str) -> bool:
    """Delete a task. Only the creator may delete."""
    _ensure()
    with _connect() as conn:
        cur = conn.execute(
            "DELETE FROM tasks WHERE id = ? AND creator_id = ?", (task_id, user_id)
        )
        return cur.rowcount > 0


# ---------- AI OA: calendar ----------

def _event_row(row: sqlite3.Row) -> dict:
    d = dict(row)
    d["attendees"] = json.loads(d.pop("attendees_json") or "[]")
    return d


def create_event(
    owner_id: str,
    title: str,
    start_at: float,
    end_at: float | None = None,
    location: str | None = None,
    attendees: Iterable[str] | None = None,
    org_id: str | None = None,
) -> dict:
    _ensure()
    eid = uuid.uuid4().hex
    now = time.time()
    attendees_json = json.dumps(list(attendees or []), ensure_ascii=False)
    with _connect() as conn:
        conn.execute(
            "INSERT INTO calendar_events (id, org_id, owner_id, title, start_at, end_at, "
            "location, attendees_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (eid, org_id, owner_id, title, start_at, end_at, location, attendees_json, now),
        )
        row = conn.execute("SELECT * FROM calendar_events WHERE id = ?", (eid,)).fetchone()
        return _event_row(row)


def list_events(owner_id: str, since: float | None = None) -> list[dict]:
    _ensure()
    with _connect() as conn:
        if since is not None:
            rows = conn.execute(
                "SELECT * FROM calendar_events WHERE owner_id = ? AND start_at >= ? "
                "ORDER BY start_at ASC",
                (owner_id, since),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM calendar_events WHERE owner_id = ? ORDER BY start_at ASC",
                (owner_id,),
            ).fetchall()
        return [_event_row(r) for r in rows]


def get_event(event_id: str) -> dict | None:
    _ensure()
    with _connect() as conn:
        row = conn.execute("SELECT * FROM calendar_events WHERE id = ?", (event_id,)).fetchone()
        return _event_row(row) if row else None


def update_event(event_id: str, owner_id: str, fields: dict) -> dict | None:
    """Update an event's editable fields and/or status. Only the owner may edit."""
    _ensure()
    allowed = ("title", "start_at", "end_at", "location", "status")
    sets = []
    args: list = []
    for key in allowed:
        if key in fields and fields[key] is not None:
            sets.append(f"{key} = ?")
            args.append(fields[key])
    if "attendees" in fields and fields["attendees"] is not None:
        sets.append("attendees_json = ?")
        args.append(json.dumps(list(fields["attendees"]), ensure_ascii=False))
    if not sets:
        return get_event(event_id)
    with _connect() as conn:
        row = conn.execute(
            "SELECT owner_id FROM calendar_events WHERE id = ?", (event_id,)
        ).fetchone()
        if row is None or row["owner_id"] != owner_id:
            return None
        conn.execute(
            f"UPDATE calendar_events SET {', '.join(sets)} WHERE id = ?", (*args, event_id)
        )
        updated = conn.execute(
            "SELECT * FROM calendar_events WHERE id = ?", (event_id,)
        ).fetchone()
        return _event_row(updated)


def delete_event(event_id: str, owner_id: str) -> bool:
    _ensure()
    with _connect() as conn:
        cur = conn.execute(
            "DELETE FROM calendar_events WHERE id = ? AND owner_id = ?", (event_id, owner_id)
        )
        return cur.rowcount > 0


# ---------- AI OA: knowledge base ----------

def create_kb_document(
    org_id: str | None,
    uploader_id: str,
    title: str,
    text_content: str,
    chunks: Iterable[str] | None = None,
    source_upload_id: str | None = None,
    embeddings: list[list[float]] | None = None,
    scope: str = "org",
) -> dict:
    _ensure()
    did = uuid.uuid4().hex
    now = time.time()
    chunk_list = list(chunks or [])
    with _connect() as conn:
        conn.execute(
            "INSERT INTO kb_documents (id, org_id, uploader_id, title, text_content, "
            "source_upload_id, scope, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (did, org_id, uploader_id, title, text_content, source_upload_id, scope, now),
        )
        for idx, chunk in enumerate(chunk_list):
            emb = None
            if embeddings is not None and idx < len(embeddings) and embeddings[idx] is not None:
                emb = json.dumps(embeddings[idx])
            conn.execute(
                "INSERT INTO kb_chunks (doc_id, chunk_index, text, embedding_json) VALUES (?, ?, ?, ?)",
                (did, idx, chunk, emb),
            )
        row = conn.execute("SELECT * FROM kb_documents WHERE id = ?", (did,)).fetchone()
        return dict(row)


def list_kb_chunks_for_org(org_id: str | None, user_id: str | None = None) -> list[dict]:
    """Chunks visible for retrieval: the org's shared (enterprise) documents plus the
    given user's own personal documents. Includes parsed embeddings."""
    _ensure()
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT c.doc_id, c.chunk_index, c.text, c.embedding_json, d.title
            FROM kb_chunks c JOIN kb_documents d ON d.id = c.doc_id
            WHERE (d.org_id IS ? AND d.scope = 'org')
               OR (d.uploader_id = ? AND d.scope = 'personal')
            ORDER BY c.doc_id, c.chunk_index
            """,
            (org_id, user_id),
        ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        raw = d.pop("embedding_json", None)
        try:
            d["embedding"] = json.loads(raw) if raw else None
        except (TypeError, ValueError):
            d["embedding"] = None
        out.append(d)
    return out


def list_kb_documents(org_id: str | None) -> list[dict]:
    """List an org's shared (enterprise) documents."""
    _ensure()
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id, org_id, uploader_id, title, source_upload_id, created_at, "
            "LENGTH(text_content) AS text_length FROM kb_documents "
            "WHERE org_id IS ? AND scope = 'org' ORDER BY created_at DESC",
            (org_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def list_personal_kb_documents(user_id: str) -> list[dict]:
    """List a user's own personal-knowledge documents (private to them)."""
    _ensure()
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id, org_id, uploader_id, title, source_upload_id, created_at, "
            "LENGTH(text_content) AS text_length FROM kb_documents "
            "WHERE uploader_id = ? AND scope = 'personal' ORDER BY created_at DESC",
            (user_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def delete_kb_document(doc_id: str, org_id: str | None) -> bool:
    _ensure()
    with _connect() as conn:
        cur = conn.execute(
            "DELETE FROM kb_documents WHERE id = ? AND org_id IS ?", (doc_id, org_id)
        )
        return cur.rowcount > 0


def delete_personal_kb_document(doc_id: str, user_id: str) -> bool:
    _ensure()
    with _connect() as conn:
        cur = conn.execute(
            "DELETE FROM kb_documents WHERE id = ? AND uploader_id = ? AND scope = 'personal'",
            (doc_id, user_id),
        )
        return cur.rowcount > 0


def search_knowledge(org_id: str | None, query: str, limit: int = 5) -> list[dict]:
    """Lexical retrieval over an org's document chunks.

    No embedding provider is assumed; chunks are scored by overlap with the query's
    terms and character bigrams (works for CJK and latin text). Good enough for an MVP.
    """
    _ensure()
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT c.doc_id, c.chunk_index, c.text, d.title
            FROM kb_chunks c JOIN kb_documents d ON d.id = c.doc_id
            WHERE d.org_id IS ?
            """,
            (org_id,),
        ).fetchall()
    terms = _query_terms(query)
    if not terms:
        return []
    scored = []
    for r in rows:
        text = str(r["text"] or "")
        low = text.lower()
        score = sum(low.count(term) for term in terms)
        if score > 0:
            scored.append({"doc_id": r["doc_id"], "title": r["title"], "text": text, "score": score})
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:limit]


def _query_terms(query: str) -> list[str]:
    q = (query or "").lower().strip()
    if not q:
        return []
    terms: set[str] = set()
    for word in re.split(r"[^0-9a-z一-鿿]+", q):
        if len(word) >= 2 and not all("一" <= ch <= "鿿" for ch in word):
            terms.add(word)
    # CJK character bigrams so Chinese queries match without a tokenizer.
    cjk = [ch for ch in q if "一" <= ch <= "鿿"]
    for i in range(len(cjk) - 1):
        terms.add(cjk[i] + cjk[i + 1])
    return list(terms)


# ---------- external contacts ----------

def _external_row(row: sqlite3.Row) -> dict:
    d = dict(row)
    d["starred"] = bool(d.get("starred"))
    return d


def create_external_contact(
    user_id: str,
    *,
    name: str,
    phone: str | None = None,
    email: str | None = None,
    company: str | None = None,
    title: str | None = None,
    avatar: str | None = None,
    contact_user_id: str | None = None,
    source: str = "manual",
    starred: bool = False,
) -> dict:
    _ensure()
    cid = uuid.uuid4().hex
    now = time.time()
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO external_contacts
                (id, user_id, contact_user_id, name, phone, email, company, title, avatar, starred, source, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (cid, user_id, contact_user_id, name, phone, email, company, title, avatar,
             1 if starred else 0, source, now),
        )
    return get_external_contact(user_id, cid) or {}


def get_external_contact(user_id: str, contact_id: str) -> dict | None:
    _ensure()
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM external_contacts WHERE id = ? AND user_id = ?",
            (contact_id, user_id),
        ).fetchone()
    return _external_row(row) if row else None


def list_external_contacts(user_id: str) -> list[dict]:
    _ensure()
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM external_contacts WHERE user_id = ? ORDER BY created_at DESC",
            (user_id,),
        ).fetchall()
    return [_external_row(r) for r in rows]


def external_contact_with_user_exists(user_id: str, contact_user_id: str) -> bool:
    _ensure()
    with _connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM external_contacts WHERE user_id = ? AND contact_user_id = ?",
            (user_id, contact_user_id),
        ).fetchone()
    return row is not None


def update_external_contact(user_id: str, contact_id: str, **fields: Any) -> bool:
    _ensure()
    allowed = {"name", "phone", "email", "company", "title", "starred"}
    sets, vals = [], []
    for key, value in fields.items():
        if key not in allowed:
            continue
        sets.append(f"{key} = ?")
        vals.append((1 if value else 0) if key == "starred" else value)
    if not sets:
        return False
    vals.extend([contact_id, user_id])
    with _connect() as conn:
        cur = conn.execute(
            f"UPDATE external_contacts SET {', '.join(sets)} WHERE id = ? AND user_id = ?", vals
        )
        return cur.rowcount > 0


def delete_external_contact(user_id: str, contact_id: str) -> bool:
    _ensure()
    with _connect() as conn:
        cur = conn.execute(
            "DELETE FROM external_contacts WHERE id = ? AND user_id = ?", (contact_id, user_id)
        )
        return cur.rowcount > 0


# ---------- contact requests ----------

def create_contact_request(from_user_id: str, to_user_id: str, message: str | None = None) -> dict:
    _ensure()
    now = time.time()
    with _connect() as conn:
        existing = conn.execute(
            "SELECT id FROM contact_requests WHERE from_user_id = ? AND to_user_id = ? AND status = 'pending'",
            (from_user_id, to_user_id),
        ).fetchone()
        if existing:
            rid = existing["id"]
        else:
            rid = uuid.uuid4().hex
            conn.execute(
                "INSERT INTO contact_requests (id, from_user_id, to_user_id, message, status, created_at) "
                "VALUES (?, ?, ?, ?, 'pending', ?)",
                (rid, from_user_id, to_user_id, message, now),
            )
    return get_contact_request(rid) or {}


def get_contact_request(request_id: str) -> dict | None:
    _ensure()
    with _connect() as conn:
        row = conn.execute("SELECT * FROM contact_requests WHERE id = ?", (request_id,)).fetchone()
    return dict(row) if row else None


def _list_contact_requests(user_id: str, incoming: bool) -> list[dict]:
    _ensure()
    mine, other = ("to_user_id", "from_user_id") if incoming else ("from_user_id", "to_user_id")
    with _connect() as conn:
        rows = conn.execute(
            f"""
            SELECT r.id, r.message, r.status, r.created_at, r.responded_at,
                   u.id AS user_id, u.username, u.real_name, u.avatar, u.email, u.company, u.title
            FROM contact_requests r
            JOIN users u ON u.id = r.{other}
            WHERE r.{mine} = ? AND r.status = 'pending'
            ORDER BY r.created_at DESC
            """,
            (user_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def list_incoming_contact_requests(user_id: str) -> list[dict]:
    return _list_contact_requests(user_id, incoming=True)


def list_outgoing_contact_requests(user_id: str) -> list[dict]:
    return _list_contact_requests(user_id, incoming=False)


def respond_contact_request(request_id: str, to_user_id: str, status: str) -> dict | None:
    _ensure()
    now = time.time()
    with _connect() as conn:
        cur = conn.execute(
            "UPDATE contact_requests SET status = ?, responded_at = ? "
            "WHERE id = ? AND to_user_id = ? AND status = 'pending'",
            (status, now, request_id, to_user_id),
        )
        if cur.rowcount == 0:
            return None
    return get_contact_request(request_id)


# ---------- contact stars (org members) ----------

def star_member(user_id: str, member_user_id: str) -> None:
    _ensure()
    with _connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO contact_stars (user_id, member_user_id, created_at) VALUES (?, ?, ?)",
            (user_id, member_user_id, time.time()),
        )


def unstar_member(user_id: str, member_user_id: str) -> bool:
    _ensure()
    with _connect() as conn:
        cur = conn.execute(
            "DELETE FROM contact_stars WHERE user_id = ? AND member_user_id = ?",
            (user_id, member_user_id),
        )
        return cur.rowcount > 0


def list_starred_member_ids(user_id: str) -> list[str]:
    _ensure()
    with _connect() as conn:
        rows = conn.execute(
            "SELECT member_user_id FROM contact_stars WHERE user_id = ?", (user_id,)
        ).fetchall()
    return [str(r["member_user_id"]) for r in rows]


def get_users_by_ids(ids: list[str]) -> list[dict]:
    _ensure()
    if not ids:
        return []
    placeholders = ",".join("?" for _ in ids)
    with _connect() as conn:
        rows = conn.execute(
            f"SELECT id, account, username, real_name, avatar, email, phone, company, title "
            f"FROM users WHERE id IN ({placeholders})",
            ids,
        ).fetchall()
    return [dict(r) for r in rows]


# ---------- instant messaging ----------

def find_or_create_direct_conversation(user_a: str, user_b: str) -> dict:
    _ensure()
    now = time.time()
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT c.id FROM conversations c
            WHERE c.type = 'direct'
              AND (SELECT COUNT(*) FROM conversation_members m WHERE m.conversation_id = c.id) = 2
              AND EXISTS (SELECT 1 FROM conversation_members m WHERE m.conversation_id = c.id AND m.user_id = ?)
              AND EXISTS (SELECT 1 FROM conversation_members m WHERE m.conversation_id = c.id AND m.user_id = ?)
            LIMIT 1
            """,
            (user_a, user_b),
        ).fetchone()
        if row:
            cid = row["id"]
        else:
            cid = uuid.uuid4().hex
            conn.execute(
                "INSERT INTO conversations (id, type, title, org_id, created_by, created_at, updated_at) "
                "VALUES (?, 'direct', NULL, NULL, ?, ?, ?)",
                (cid, user_a, now, now),
            )
            for uid in (user_a, user_b):
                conn.execute(
                    "INSERT OR IGNORE INTO conversation_members "
                    "(conversation_id, user_id, role, last_read_at, joined_at) VALUES (?, ?, 'member', 0, ?)",
                    (cid, uid, now),
                )
    return get_conversation(cid) or {}


def create_group_conversation(creator_id: str, title: str, member_ids: list[str]) -> dict:
    _ensure()
    now = time.time()
    cid = uuid.uuid4().hex
    members = list(dict.fromkeys([creator_id, *member_ids]))
    with _connect() as conn:
        conn.execute(
            "INSERT INTO conversations (id, type, title, org_id, created_by, created_at, updated_at) "
            "VALUES (?, 'group', ?, NULL, ?, ?, ?)",
            (cid, title, creator_id, now, now),
        )
        for uid in members:
            role = "owner" if uid == creator_id else "member"
            conn.execute(
                "INSERT OR IGNORE INTO conversation_members "
                "(conversation_id, user_id, role, last_read_at, joined_at) VALUES (?, ?, ?, 0, ?)",
                (cid, uid, role, now),
            )
    return get_conversation(cid) or {}


def get_conversation(conversation_id: str) -> dict | None:
    _ensure()
    with _connect() as conn:
        row = conn.execute("SELECT * FROM conversations WHERE id = ?", (conversation_id,)).fetchone()
    return dict(row) if row else None


def is_conversation_member(conversation_id: str, user_id: str) -> bool:
    _ensure()
    with _connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM conversation_members WHERE conversation_id = ? AND user_id = ?",
            (conversation_id, user_id),
        ).fetchone()
    return row is not None


def list_conversation_member_ids(conversation_id: str) -> list[str]:
    _ensure()
    with _connect() as conn:
        rows = conn.execute(
            "SELECT user_id FROM conversation_members WHERE conversation_id = ?", (conversation_id,)
        ).fetchall()
    return [str(r["user_id"]) for r in rows]


def list_conversation_members(conversation_id: str) -> list[dict]:
    _ensure()
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT u.id, u.account, u.username, u.real_name, u.avatar, u.email, u.company, u.title, m.role, m.joined_at
            FROM conversation_members m
            JOIN users u ON u.id = m.user_id
            WHERE m.conversation_id = ?
            ORDER BY CASE m.role WHEN 'owner' THEN 0 ELSE 1 END, m.joined_at ASC
            """,
            (conversation_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def add_conversation_members(conversation_id: str, member_ids: list[str]) -> None:
    _ensure()
    now = time.time()
    with _connect() as conn:
        for uid in member_ids:
            conn.execute(
                "INSERT OR IGNORE INTO conversation_members "
                "(conversation_id, user_id, role, last_read_at, joined_at) VALUES (?, ?, 'member', 0, ?)",
                (conversation_id, uid, now),
            )
        conn.execute("UPDATE conversations SET updated_at = ? WHERE id = ?", (now, conversation_id))


def add_im_message(conversation_id: str, sender_id: str, content: str, kind: str = "text") -> dict:
    _ensure()
    mid = uuid.uuid4().hex
    now = time.time()
    with _connect() as conn:
        conn.execute(
            "INSERT INTO im_messages (id, conversation_id, sender_id, kind, content, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (mid, conversation_id, sender_id, kind, content, now),
        )
        conn.execute("UPDATE conversations SET updated_at = ? WHERE id = ?", (now, conversation_id))
        # The sender has implicitly read their own message.
        conn.execute(
            "UPDATE conversation_members SET last_read_at = ? WHERE conversation_id = ? AND user_id = ?",
            (now, conversation_id, sender_id),
        )
    return {
        "id": mid, "conversation_id": conversation_id, "sender_id": sender_id,
        "kind": kind, "content": content, "created_at": now,
    }


def conversation_has_file(conversation_id: str, file_id: str) -> bool:
    """True if a file message in this conversation references the given upload id."""
    _ensure()
    if not re.fullmatch(r"[0-9a-f]{32}", file_id or ""):
        return False
    with _connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM im_messages WHERE conversation_id = ? AND kind = 'file' "
            "AND content LIKE ? LIMIT 1",
            (conversation_id, f'%"file_id": "{file_id}"%'),
        ).fetchone()
    return row is not None


def list_im_messages(conversation_id: str, before: float | None = None, limit: int = 50) -> list[dict]:
    _ensure()
    limit = max(1, min(int(limit), 200))
    with _connect() as conn:
        if before is None:
            rows = conn.execute(
                "SELECT id, conversation_id, sender_id, kind, content, created_at FROM im_messages "
                "WHERE conversation_id = ? ORDER BY created_at DESC LIMIT ?",
                (conversation_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, conversation_id, sender_id, kind, content, created_at FROM im_messages "
                "WHERE conversation_id = ? AND created_at < ? ORDER BY created_at DESC LIMIT ?",
                (conversation_id, before, limit),
            ).fetchall()
    return [dict(r) for r in reversed(rows)]


def mark_conversation_read(conversation_id: str, user_id: str, ts: float | None = None) -> None:
    _ensure()
    stamp = ts if ts is not None else time.time()
    with _connect() as conn:
        conn.execute(
            "UPDATE conversation_members SET last_read_at = ? WHERE conversation_id = ? AND user_id = ?",
            (stamp, conversation_id, user_id),
        )


def list_conversations_for_user(user_id: str) -> list[dict]:
    _ensure()
    result: list[dict] = []
    with _connect() as conn:
        conv_rows = conn.execute(
            """
            SELECT c.id, c.type, c.title, c.created_by, c.created_at, c.updated_at, m.last_read_at
            FROM conversation_members m
            JOIN conversations c ON c.id = m.conversation_id
            WHERE m.user_id = ?
            ORDER BY c.updated_at DESC
            """,
            (user_id,),
        ).fetchall()
        for c in conv_rows:
            cid = c["id"]
            last = conn.execute(
                "SELECT sender_id, kind, content, created_at FROM im_messages "
                "WHERE conversation_id = ? ORDER BY created_at DESC LIMIT 1",
                (cid,),
            ).fetchone()
            unread = conn.execute(
                "SELECT COUNT(*) AS n FROM im_messages "
                "WHERE conversation_id = ? AND created_at > ? AND sender_id != ?",
                (cid, c["last_read_at"] or 0, user_id),
            ).fetchone()["n"]
            member_count = conn.execute(
                "SELECT COUNT(*) AS n FROM conversation_members WHERE conversation_id = ?", (cid,)
            ).fetchone()["n"]
            peer = None
            peer_last_read_at = None
            if c["type"] == "direct":
                peer = conn.execute(
                    """
                    SELECT u.id, u.username, u.real_name, u.avatar, mm.last_read_at
                    FROM conversation_members mm
                    JOIN users u ON u.id = mm.user_id
                    WHERE mm.conversation_id = ? AND mm.user_id != ?
                    LIMIT 1
                    """,
                    (cid, user_id),
                ).fetchone()
                if peer is not None:
                    peer_last_read_at = peer["last_read_at"]
            result.append({
                "id": cid,
                "type": c["type"],
                "title": c["title"],
                "created_by": c["created_by"],
                "updated_at": c["updated_at"],
                "member_count": int(member_count),
                "peer": {
                    "id": peer["id"],
                    "username": peer["username"],
                    "real_name": peer["real_name"],
                    "avatar": peer["avatar"],
                } if peer else None,
                "peer_last_read_at": peer_last_read_at,
                "last_message": dict(last) if last else None,
                "unread": int(unread),
            })
    return result


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
                        DROP TABLE IF EXISTS kb_chunks;
                        DROP TABLE IF EXISTS kb_documents;
                        DROP TABLE IF EXISTS calendar_events;
                        DROP TABLE IF EXISTS tasks;
                        DROP TABLE IF EXISTS approval_steps;
                        DROP TABLE IF EXISTS approvals;
                        DROP TABLE IF EXISTS im_messages;
                        DROP TABLE IF EXISTS conversation_members;
                        DROP TABLE IF EXISTS conversations;
                        DROP TABLE IF EXISTS contact_stars;
                        DROP TABLE IF EXISTS contact_requests;
                        DROP TABLE IF EXISTS external_contacts;
                        DROP TABLE IF EXISTS org_members;
                        DROP TABLE IF EXISTS organizations;
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
