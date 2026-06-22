"""API routes."""
from __future__ import annotations

import asyncio
import os
from typing import AsyncIterator
from urllib.parse import quote

import anthropic
from fastapi import APIRouter, Body, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from sse_starlette.sse import EventSourceResponse

from marketing_agent.file_inputs import build_prompt_addendum, extract
from marketing_agent.orchestrator import run_orchestrator

from . import auth, db, sessions, uploads
from .streaming import orchestrator_event_stream, to_sse

router = APIRouter(prefix="/api")


def _client() -> anthropic.Anthropic:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise HTTPException(500, "ANTHROPIC_API_KEY not configured on server.")
    return anthropic.Anthropic()


@router.get("/health")
def health() -> dict:
    return {"status": "ok"}


# ---------- auth ----------

@router.post("/auth/register")
def register(payload: dict = Body(...)) -> dict:
    account = auth.validate_account(str(payload.get("account") or ""))
    auth.validate_password(str(payload.get("password") or ""))
    if db.get_user_by_account(account) is not None:
        raise HTTPException(409, "账号已存在。")
    profile = {
        "account": account,
        "password_hash": auth.hash_password(str(payload.get("password") or "")),
        "username": auth.validate_required_text(payload.get("username"), "用户名"),
        "real_name": auth.validate_required_text(payload.get("real_name"), "真实姓名"),
        "id_card": auth.validate_china_id_card(payload.get("id_card")),
        "avatar": auth.validate_avatar(payload.get("avatar")),
        **auth.validate_contact_fields(payload),
    }
    user = db.create_user(**profile)
    token = auth.issue_token(user["id"])
    return {"token": token, "user": auth.public_user(user)}


@router.post("/auth/login")
def login(payload: dict = Body(...)) -> dict:
    account = auth.validate_account(str(payload.get("account") or ""))
    password = str(payload.get("password") or "")
    user = db.get_user_by_account(account)
    if user is None or not auth.verify_password(password, user["password_hash"]):
        raise HTTPException(401, "账号或密码不正确。")
    token = auth.issue_token(user["id"])
    return {"token": token, "user": auth.public_user(user)}


@router.post("/auth/logout")
def logout(request: Request) -> dict:
    token = auth.token_from_request(request)
    if token:
        db.delete_auth_token(token)
    return {"ok": True}


@router.get("/auth/me")
def me(request: Request) -> dict:
    return {"user": auth.public_user(auth.require_user(request))}


@router.patch("/auth/me")
def update_me(request: Request, payload: dict = Body(...)) -> dict:
    user = auth.require_user(request)
    fields = {
        "username": auth.validate_required_text(payload.get("username"), "用户名"),
        "avatar": auth.validate_avatar(payload.get("avatar")),
        **auth.validate_contact_fields(payload),
    }
    password = str(payload.get("password") or "")
    if password:
        fields["password_hash"] = auth.hash_password(auth.validate_password(password))
    updated = db.update_user_profile(user["id"], **fields)
    if updated is None:
        raise HTTPException(404, "User not found.")
    return {"user": auth.public_user(updated)}


@router.delete("/auth/me")
def delete_me(request: Request, payload: dict = Body(...)) -> dict:
    user = auth.require_user(request)
    if str(payload.get("confirmation") or "").strip() != "我确认注销账号":
        raise HTTPException(400, "请输入确认文本。")
    db.delete_user(user["id"])
    return {"deleted": user["account"]}


@router.get("/auth/avatar")
def avatar_lookup(account: str) -> dict:
    user = db.get_user_by_account(account.strip())
    if user is None:
        return {"exists": False, "avatar": None, "username": None}
    return {"exists": True, "avatar": user.get("avatar"), "username": user.get("username")}


# ---------- groups ----------

@router.get("/groups")
def list_groups(request: Request) -> list[dict]:
    user = auth.require_user(request)
    return db.list_groups(user["id"])


@router.post("/groups")
def create_group(request: Request, payload: dict = Body(...)) -> dict:
    user = auth.require_user(request)
    name = (payload.get("name") or "").strip() or "New group"
    return db.create_group(user["id"], name)


@router.patch("/groups/{group_id}")
def rename_group(request: Request, group_id: str, payload: dict = Body(...)) -> dict:
    user = auth.require_user(request)
    name = (payload.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "name is required")
    if not db.rename_group(user["id"], group_id, name):
        raise HTTPException(404, "Group not found.")
    return {"id": group_id, "name": name}


@router.delete("/groups/{group_id}")
def delete_group(request: Request, group_id: str) -> dict:
    user = auth.require_user(request)
    if not db.delete_group(user["id"], group_id):
        raise HTTPException(404, "Group not found.")
    return {"deleted": group_id}


# ---------- sessions ----------

@router.get("/sessions")
def list_sessions(request: Request) -> list[dict]:
    user = auth.require_user(request)
    return db.list_sessions(user["id"])


@router.post("/sessions")
def create_session(request: Request, payload: dict | None = Body(None)) -> dict:
    user = auth.require_user(request)
    name = (payload or {}).get("name") or "New chat"
    group_id = (payload or {}).get("group_id")
    if group_id and db.get_group(user["id"], group_id) is None:
        raise HTTPException(404, "Group not found.")
    sid = sessions.create(user["id"], name=name, group_id=group_id)
    return {"session_id": sid, "name": name, "group_id": group_id}


@router.patch("/sessions/{session_id}")
def update_session(request: Request, session_id: str, payload: dict = Body(...)) -> dict:
    user = auth.require_user(request)
    if db.get_session(session_id, user["id"]) is None:
        raise HTTPException(404, "Session not found.")
    name = payload.get("name")
    group_id = payload.get("group_id", ...)  # ... means leave unchanged
    if group_id not in (None, ...) and db.get_group(user["id"], group_id) is None:
        raise HTTPException(404, "Group not found.")
    db.update_session(session_id, user_id=user["id"], name=name, group_id=group_id)
    return db.get_session(session_id, user["id"]) or {}


@router.delete("/sessions/{session_id}")
def delete_session(request: Request, session_id: str) -> dict:
    user = auth.require_user(request)
    if not sessions.delete(session_id, user["id"]):
        raise HTTPException(404, "Session not found.")
    return {"deleted": session_id}


@router.get("/sessions/{session_id}/messages")
def get_session_messages(request: Request, session_id: str) -> dict:
    user = auth.require_user(request)
    if db.get_session(session_id, user["id"]) is None:
        raise HTTPException(404, "Session not found.")
    rows = db.list_messages(session_id)
    artifacts = [
        {
            "artifact_id": rec["id"],
            "filename": rec["filename"],
            "mime": rec["mime"],
        }
    for rec in db.list_artifacts(session_id, user["id"])
    ]
    # For the UI, project assistant content (list of blocks) to a plain text string.
    out = []
    for row in rows:
        content = row["content"]
        role = row["role"]
        try:
            import json as _json

            parsed = _json.loads(content)
            if isinstance(parsed, list):
                # Pick text blocks from assistant content; ignore tool_results for UI display.
                texts = []
                for block in parsed:
                    if isinstance(block, dict):
                        if block.get("type") == "text" and block.get("text"):
                            texts.append(block["text"])
                if texts:
                    out.append({"role": role, "content": "\n\n".join(texts)})
                # Skip tool-result-only user turns from UI rendering.
                continue
            content = parsed if isinstance(parsed, str) else content
        except Exception:  # noqa: BLE001
            pass
        if role in ("user", "assistant") and isinstance(content, str):
            out.append({"role": role, "content": content})
    if artifacts:
        for message in reversed(out):
            if message["role"] == "assistant":
                message["artifacts"] = artifacts
                break
    return {"session_id": session_id, "messages": out}


# ---------- uploads ----------

@router.post("/upload")
async def upload_file(request: Request, file: UploadFile = File(...)) -> dict:
    user = auth.require_user(request)
    if not file.filename:
        raise HTTPException(400, "Missing filename.")
    content = await file.read(uploads.MAX_UPLOAD_BYTES + 1)
    if not content:
        raise HTTPException(400, "Empty file.")
    if len(content) > uploads.MAX_UPLOAD_BYTES:
        limit_mb = uploads.MAX_UPLOAD_BYTES // (1024 * 1024)
        raise HTTPException(413, f"File exceeds the {limit_mb} MB upload limit.")
    try:
        saved = uploads.save(content, file.filename, file.content_type)
        path = uploads.resolve(saved["file_id"])
        if path is None:
            raise HTTPException(500, "Upload failed.")
        db.add_upload(user["id"], saved["file_id"], saved["original_name"], saved["mime"], saved["ext"], saved["size"], str(path))
        return saved
    except uploads.UploadValidationError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/uploads/{file_id}/download")
def download_upload(request: Request, file_id: str):
    user = auth.require_user(request)
    rec = db.get_upload(file_id, user["id"])
    if rec is None:
        raise HTTPException(404, "File not found.")
    from pathlib import Path
    path = Path(rec["path"])
    return FileResponse(
        path,
        filename=path.name.split("_", 1)[-1] if "_" in path.name else path.name,
    )


@router.get("/uploads/{file_id}/preview")
def preview_upload(request: Request, file_id: str):
    """Inline-serve an uploaded file (e.g. PDF iframe, image tag)."""
    user = auth.require_user(request)
    rec = db.get_upload(file_id, user["id"])
    if rec is None:
        raise HTTPException(404, "File not found.")
    from pathlib import Path
    path = Path(rec["path"])
    return FileResponse(path)


# ---------- artifacts ----------

@router.get("/artifacts/{artifact_id}/download")
def download_artifact(request: Request, artifact_id: str):
    user = auth.require_user(request)
    rec = db.get_artifact(artifact_id, user["id"])
    if rec is None:
        raise HTTPException(404, "Artifact not found.")
    headers = {
        "Content-Disposition": f'attachment; filename="{quote(rec["filename"])}"'
    }
    return FileResponse(rec["path"], media_type=rec["mime"], headers=headers, filename=rec["filename"])


@router.get("/artifacts/{artifact_id}/preview")
def preview_artifact(request: Request, artifact_id: str):
    user = auth.require_user(request)
    rec = db.get_artifact(artifact_id, user["id"])
    if rec is None:
        raise HTTPException(404, "Artifact not found.")
    return FileResponse(rec["path"], media_type=rec["mime"])


@router.get("/artifacts/{artifact_id}")
def get_artifact_meta(request: Request, artifact_id: str) -> dict:
    user = auth.require_user(request)
    rec = db.get_artifact(artifact_id, user["id"])
    if rec is None:
        raise HTTPException(404, "Artifact not found.")
    # Don't leak filesystem path
    return {k: v for k, v in rec.items() if k != "path"}


def _attached_ids(file_ids: str | list[str] | None, csv_id: str | None = None) -> list[str]:
    ids: list[str] = []
    if isinstance(file_ids, str):
        ids.extend([fid for fid in file_ids.split(",") if fid.strip()])
    elif isinstance(file_ids, list):
        ids.extend([str(fid) for fid in file_ids if str(fid).strip()])
    if csv_id and csv_id not in ids:
        ids.append(csv_id)
    return ids


def _build_user_message(user_id: str, prompt: str, file_ids: str | list[str] | None, csv_id: str | None = None):
    extracted: list[dict] = []
    image_blocks: list[dict] = []

    for fid in _attached_ids(file_ids, csv_id):
        rec = db.get_upload(fid, user_id)
        if rec is None:
            raise HTTPException(404, f"file_id '{fid}' not found.")
        from pathlib import Path
        path = Path(rec["path"])
        info = extract(path)
        if info["kind"] == "image":
            image_blocks.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": info["media_type"],
                    "data": info["data_b64"],
                },
            })
        else:
            extracted.append(info)
            if info["ext"] == ".csv":
                extracted.append({
                    "kind": "text",
                    "name": info["name"],
                    "text": f"(CSV available at: {path})",
                })

    addendum = build_prompt_addendum(extracted) if extracted else ""
    if image_blocks:
        return [{"type": "text", "text": prompt + addendum}, *image_blocks]
    return prompt + addendum


def _persist_user_prompt(user_id: str, session_id: str, prompt: str) -> None:
    rows = db.list_messages(session_id)
    last = rows[-1] if rows else None
    if not last or last["role"] != "user" or last["content"] != prompt:
        db.add_message(session_id, "user", prompt)
    db.update_session(session_id, user_id=user_id, name=_derive_name(session_id, prompt), touch=True)


def _session_aware_on_event_factory(user_id: str, session_id: str):
    accumulated_text: list[str] = []

    def wrapper(inner_emit):
        def emit(event: str, payload: dict):
            if event == "assistant_delta":
                accumulated_text.append(str(payload.get("delta", "")))
            elif event == "result":
                final_text = str(payload.get("text", ""))
                if final_text:
                    db.add_message(session_id, "assistant", final_text)
            elif event == "error":
                message = str(payload.get("message", "")).strip()
                if message:
                    db.add_message(session_id, "assistant", f"**Error:** {message}")
            elif event == "artifact_created":
                try:
                    aid = payload.get("artifact_id")
                    if aid:
                        with db._connect() as conn:  # type: ignore[attr-defined]
                            conn.execute(
                                "UPDATE artifacts SET session_id = ? WHERE id = ? AND user_id = ?",
                                (session_id, aid, user_id),
                            )
                except Exception:  # noqa: BLE001
                    pass
            inner_emit(event, payload)
        return emit
    return wrapper


async def _with_current_user(user_id: str, stream: AsyncIterator[dict]) -> AsyncIterator[dict]:
    token = db.CURRENT_USER_ID.set(user_id)
    try:
        async for event in stream:
            yield event
    finally:
        db.CURRENT_USER_ID.reset(token)


# ---------- stream ----------

@router.get("/sessions/{session_id}/stream")
async def stream_session(
    request: Request,
    session_id: str,
    prompt: str,
    csv_id: str | None = None,
    file_ids: str | None = None,
):
    user = auth.require_user(request)
    conversation = sessions.get(session_id, user["id"])
    if conversation is None:
        raise HTTPException(404, "Session not found.")
    if not prompt.strip():
        raise HTTPException(400, "Empty prompt.")

    user_message = _build_user_message(user["id"], prompt, file_ids, csv_id)
    _persist_user_prompt(user["id"], session_id, prompt)

    # Build user_message — string if no images, else list-of-blocks.
    client = _client()

    # Wrap the orchestrator's on_event to also persist assistant turns + bind artifacts to session.
    event_stream = orchestrator_event_stream(
        client,
        conversation,
        user_message,
        request=request,
        on_event_wrapper=_session_aware_on_event_factory(user["id"], session_id),
    )
    return EventSourceResponse(to_sse(_with_current_user(user["id"], event_stream)))


@router.post("/sessions/{session_id}/complete")
async def complete_session(request: Request, session_id: str, payload: dict = Body(...)) -> dict:
    user = auth.require_user(request)
    conversation = sessions.get(session_id, user["id"])
    if conversation is None:
        raise HTTPException(404, "Session not found.")
    prompt = str(payload.get("prompt") or "").strip()
    if not prompt:
        raise HTTPException(400, "Empty prompt.")

    user_message = _build_user_message(
        user["id"],
        prompt,
        payload.get("file_ids"),
        payload.get("csv_id"),
    )
    _persist_user_prompt(user["id"], session_id, prompt)
    client = _client()
    events: list[dict] = []
    final_text = ""
    error_text = ""

    def emit(event: str, event_payload: dict) -> None:
        nonlocal final_text, error_text
        events.append({"event": event, "payload": event_payload})
        if event == "result":
            final_text = str(event_payload.get("text", ""))
        elif event == "error":
            error_text = str(event_payload.get("message", "")).strip()

    recorder = _session_aware_on_event_factory(user["id"], session_id)(emit)
    token = db.CURRENT_USER_ID.set(user["id"])
    try:
        await asyncio.to_thread(run_orchestrator, client, conversation, user_message, recorder)
    except Exception as exc:  # noqa: BLE001
        recorder("error", {"message": str(exc)})
    finally:
        db.CURRENT_USER_ID.reset(token)

    if error_text and not final_text:
        return {"ok": False, "text": f"**Error:** {error_text}", "events": events}
    return {"ok": True, "text": final_text, "events": events}


def _derive_name(session_id: str, prompt: str) -> str | None:
    """If session is still untitled, auto-name from first user message (first 40 chars)."""
    rec = db.get_session(session_id)
    if not rec:
        return None
    if rec["name"] and rec["name"] != "New chat":
        return None
    snippet = prompt.strip().splitlines()[0][:40] if prompt.strip() else "New chat"
    return snippet or "New chat"
