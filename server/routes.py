"""API routes."""
from __future__ import annotations

import asyncio
import os
from urllib.parse import quote

import anthropic
from fastapi import APIRouter, Body, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from sse_starlette.sse import EventSourceResponse

from marketing_agent.file_inputs import build_prompt_addendum, extract
from marketing_agent.orchestrator import run_orchestrator

from . import db, sessions, uploads
from .streaming import orchestrator_event_stream, to_sse

router = APIRouter(prefix="/api")


def _client() -> anthropic.Anthropic:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise HTTPException(500, "ANTHROPIC_API_KEY not configured on server.")
    return anthropic.Anthropic()


@router.get("/health")
def health() -> dict:
    return {"status": "ok"}


# ---------- groups ----------

@router.get("/groups")
def list_groups() -> list[dict]:
    return db.list_groups()


@router.post("/groups")
def create_group(payload: dict = Body(...)) -> dict:
    name = (payload.get("name") or "").strip() or "New group"
    return db.create_group(name)


@router.patch("/groups/{group_id}")
def rename_group(group_id: str, payload: dict = Body(...)) -> dict:
    name = (payload.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "name is required")
    if not db.rename_group(group_id, name):
        raise HTTPException(404, "Group not found.")
    return {"id": group_id, "name": name}


@router.delete("/groups/{group_id}")
def delete_group(group_id: str) -> dict:
    if not db.delete_group(group_id):
        raise HTTPException(404, "Group not found.")
    return {"deleted": group_id}


# ---------- sessions ----------

@router.get("/sessions")
def list_sessions() -> list[dict]:
    return db.list_sessions()


@router.post("/sessions")
def create_session(payload: dict | None = Body(None)) -> dict:
    name = (payload or {}).get("name") or "New chat"
    group_id = (payload or {}).get("group_id")
    sid = sessions.create(name=name, group_id=group_id)
    return {"session_id": sid, "name": name, "group_id": group_id}


@router.patch("/sessions/{session_id}")
def update_session(session_id: str, payload: dict = Body(...)) -> dict:
    if db.get_session(session_id) is None:
        raise HTTPException(404, "Session not found.")
    name = payload.get("name")
    group_id = payload.get("group_id", ...)  # ... means leave unchanged
    db.update_session(session_id, name=name, group_id=group_id)
    return db.get_session(session_id) or {}


@router.delete("/sessions/{session_id}")
def delete_session(session_id: str) -> dict:
    if not sessions.delete(session_id):
        raise HTTPException(404, "Session not found.")
    return {"deleted": session_id}


@router.get("/sessions/{session_id}/messages")
def get_session_messages(session_id: str) -> dict:
    if db.get_session(session_id) is None:
        raise HTTPException(404, "Session not found.")
    rows = db.list_messages(session_id)
    artifacts = [
        {
            "artifact_id": rec["id"],
            "filename": rec["filename"],
            "mime": rec["mime"],
        }
        for rec in db.list_artifacts(session_id)
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
async def upload_file(file: UploadFile = File(...)) -> dict:
    if not file.filename:
        raise HTTPException(400, "Missing filename.")
    content = await file.read(uploads.MAX_UPLOAD_BYTES + 1)
    if not content:
        raise HTTPException(400, "Empty file.")
    if len(content) > uploads.MAX_UPLOAD_BYTES:
        limit_mb = uploads.MAX_UPLOAD_BYTES // (1024 * 1024)
        raise HTTPException(413, f"File exceeds the {limit_mb} MB upload limit.")
    try:
        return uploads.save(content, file.filename, file.content_type)
    except uploads.UploadValidationError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/uploads/{file_id}/download")
def download_upload(file_id: str):
    path = uploads.resolve(file_id)
    if path is None:
        raise HTTPException(404, "File not found.")
    return FileResponse(
        path,
        filename=path.name.split("_", 1)[-1] if "_" in path.name else path.name,
    )


@router.get("/uploads/{file_id}/preview")
def preview_upload(file_id: str):
    """Inline-serve an uploaded file (e.g. PDF iframe, image tag)."""
    path = uploads.resolve(file_id)
    if path is None:
        raise HTTPException(404, "File not found.")
    return FileResponse(path)


# ---------- artifacts ----------

@router.get("/artifacts/{artifact_id}/download")
def download_artifact(artifact_id: str):
    rec = db.get_artifact(artifact_id)
    if rec is None:
        raise HTTPException(404, "Artifact not found.")
    headers = {
        "Content-Disposition": f'attachment; filename="{quote(rec["filename"])}"'
    }
    return FileResponse(rec["path"], media_type=rec["mime"], headers=headers, filename=rec["filename"])


@router.get("/artifacts/{artifact_id}/preview")
def preview_artifact(artifact_id: str):
    rec = db.get_artifact(artifact_id)
    if rec is None:
        raise HTTPException(404, "Artifact not found.")
    return FileResponse(rec["path"], media_type=rec["mime"])


@router.get("/artifacts/{artifact_id}")
def get_artifact_meta(artifact_id: str) -> dict:
    rec = db.get_artifact(artifact_id)
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


def _build_user_message(prompt: str, file_ids: str | list[str] | None, csv_id: str | None = None):
    extracted: list[dict] = []
    image_blocks: list[dict] = []

    for fid in _attached_ids(file_ids, csv_id):
        path = uploads.resolve(fid)
        if path is None:
            raise HTTPException(404, f"file_id '{fid}' not found.")
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


def _persist_user_prompt(session_id: str, prompt: str) -> None:
    rows = db.list_messages(session_id)
    last = rows[-1] if rows else None
    if not last or last["role"] != "user" or last["content"] != prompt:
        db.add_message(session_id, "user", prompt)
    db.update_session(session_id, name=_derive_name(session_id, prompt), touch=True)


def _session_aware_on_event_factory(session_id: str):
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
                                "UPDATE artifacts SET session_id = ? WHERE id = ?",
                                (session_id, aid),
                            )
                except Exception:  # noqa: BLE001
                    pass
            inner_emit(event, payload)
        return emit
    return wrapper


# ---------- stream ----------

@router.get("/sessions/{session_id}/stream")
async def stream_session(
    request: Request,
    session_id: str,
    prompt: str,
    csv_id: str | None = None,
    file_ids: str | None = None,
):
    conversation = sessions.get(session_id)
    if conversation is None:
        raise HTTPException(404, "Session not found.")
    if not prompt.strip():
        raise HTTPException(400, "Empty prompt.")

    user_message = _build_user_message(prompt, file_ids, csv_id)
    _persist_user_prompt(session_id, prompt)

    # Build user_message — string if no images, else list-of-blocks.
    client = _client()

    # Wrap the orchestrator's on_event to also persist assistant turns + bind artifacts to session.
    event_stream = orchestrator_event_stream(
        client,
        conversation,
        user_message,
        request=request,
        on_event_wrapper=_session_aware_on_event_factory(session_id),
    )
    return EventSourceResponse(to_sse(event_stream))


@router.post("/sessions/{session_id}/complete")
async def complete_session(session_id: str, payload: dict = Body(...)) -> dict:
    conversation = sessions.get(session_id)
    if conversation is None:
        raise HTTPException(404, "Session not found.")
    prompt = str(payload.get("prompt") or "").strip()
    if not prompt:
        raise HTTPException(400, "Empty prompt.")

    user_message = _build_user_message(
        prompt,
        payload.get("file_ids"),
        payload.get("csv_id"),
    )
    _persist_user_prompt(session_id, prompt)
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

    recorder = _session_aware_on_event_factory(session_id)(emit)
    try:
        await asyncio.to_thread(run_orchestrator, client, conversation, user_message, recorder)
    except Exception as exc:  # noqa: BLE001
        recorder("error", {"message": str(exc)})

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
