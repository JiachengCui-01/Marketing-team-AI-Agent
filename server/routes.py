"""API routes."""
from __future__ import annotations

import os

import anthropic
from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from sse_starlette.sse import EventSourceResponse

from . import sessions, uploads
from .streaming import orchestrator_event_stream, to_sse

router = APIRouter(prefix="/api")


def _client() -> anthropic.Anthropic:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise HTTPException(500, "ANTHROPIC_API_KEY not configured on server.")
    return anthropic.Anthropic()


@router.get("/health")
def health() -> dict:
    return {"status": "ok"}


@router.post("/sessions")
def create_session() -> dict:
    return {"session_id": sessions.create()}


@router.delete("/sessions/{session_id}")
def delete_session(session_id: str) -> dict:
    if not sessions.delete(session_id):
        raise HTTPException(404, "Session not found.")
    return {"deleted": session_id}


@router.post("/upload")
async def upload_csv(file: UploadFile = File(...)) -> dict:
    if not file.filename:
        raise HTTPException(400, "Missing filename.")

    content = await file.read(uploads.MAX_UPLOAD_BYTES + 1)
    if not content:
        raise HTTPException(400, "Empty file.")
    if len(content) > uploads.MAX_UPLOAD_BYTES:
        limit_mb = uploads.MAX_UPLOAD_BYTES // (1024 * 1024)
        raise HTTPException(413, f"CSV exceeds the {limit_mb} MB upload limit.")

    try:
        return uploads.save(content, file.filename, file.content_type)
    except uploads.UploadValidationError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/sessions/{session_id}/stream")
async def stream_session(
    request: Request,
    session_id: str,
    prompt: str,
    csv_id: str | None = None,
):
    conversation = sessions.get(session_id)
    if conversation is None:
        raise HTTPException(404, "Session not found.")
    if not prompt.strip():
        raise HTTPException(400, "Empty prompt.")

    full_prompt = prompt
    if csv_id:
        csv_path = uploads.resolve(csv_id)
        if csv_path is None:
            raise HTTPException(404, f"CSV file_id '{csv_id}' not found.")
        full_prompt = f"{prompt}\n\n(Campaign CSV available at: {csv_path})"

    client = _client()
    event_stream = orchestrator_event_stream(client, conversation, full_prompt, request=request)
    return EventSourceResponse(to_sse(event_stream))
