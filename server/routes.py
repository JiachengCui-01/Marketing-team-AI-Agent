"""API routes."""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import AsyncIterator
from urllib.parse import quote

import anthropic
from fastapi import APIRouter, Body, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from sse_starlette.sse import EventSourceResponse

from marketing_agent.agents.image_skills import IMAGE_SKILLS, select_image_skill
from marketing_agent.file_inputs import build_prompt_addendum, extract
from marketing_agent.orchestrator import run_orchestrator
from marketing_agent.tools import image_gen
from marketing_agent.tools.pdf_tool import generate_pdf

from . import auth, clarify, db, im_hub, image_processing, image_serve, llm, marketing_skills, memory, news, sessions, uploads
from .streaming import HEARTBEAT_INTERVAL_SECONDS, orchestrator_event_stream, to_sse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")

# Keep strong references to fire-and-forget background tasks so they are not
# garbage-collected mid-flight.
_BACKGROUND_TASKS: set[asyncio.Task] = set()


def _client() -> anthropic.Anthropic:
    client = llm.get_client()
    if client is None:
        raise HTTPException(500, "ANTHROPIC_API_KEY not configured on server.")
    return client


def _schedule_memory_update(user_id: str, prompt: str) -> None:
    """Learn long-term memory off the request path so it never adds latency."""

    async def _run() -> None:
        try:
            await asyncio.to_thread(memory.update_long_term_marketing_memory, user_id, prompt)
        except Exception:  # noqa: BLE001
            logger.exception("background long-term memory update failed")

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        memory.update_long_term_marketing_memory(user_id, prompt)
        return
    task = loop.create_task(_run())
    _BACKGROUND_TASKS.add(task)
    task.add_done_callback(_BACKGROUND_TASKS.discard)


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
    if user is None:
        raise HTTPException(404, "账号不存在。")
    if not auth.verify_password(password, user["password_hash"]):
        raise HTTPException(401, "密码不正确。")
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


# ---------- memory ----------

def _full_profile(profile: dict) -> dict:
    """Ensure every canonical field is present (empty list if unset)."""
    return {field: list(profile.get(field, [])) for field in memory.MARKETING_PROFILE_FIELDS}


def _marketing_memory_payload(user_id: str, updated_at: float | None) -> dict:
    """Standard response: manual (editable), learned (auto), and merged view.

    ``profile`` mirrors ``manual`` for backward compatibility with the editable
    settings UI; ``merged`` is what actually gets injected into model turns.
    All views expose every canonical field so the UI can render consistently.
    """
    manual = _full_profile(memory.canonicalize_profile((db.get_user_marketing_memory(user_id) or {}).get("profile") or {}))
    settings = db.get_user_memory_settings(user_id)
    return {
        "profile": manual,
        "manual": manual,
        "learned": _full_profile(memory.derive_learned_profile(user_id)),
        "merged": _full_profile(memory.merged_profile(user_id)),
        "enabled": settings["long_term_enabled"],
        "updated_at": updated_at,
    }


@router.get("/memory/marketing")
def get_marketing_memory(request: Request) -> dict:
    user = auth.require_user(request)
    rec = db.get_user_marketing_memory(user["id"])
    return _marketing_memory_payload(user["id"], (rec or {}).get("updated_at"))


@router.put("/memory/marketing")
def save_marketing_memory(request: Request, payload: dict = Body(...)) -> dict:
    user = auth.require_user(request)
    if "enabled" in payload:
        db.set_user_memory_enabled(user["id"], bool(payload.get("enabled")))
    raw_profile = payload.get("profile") if isinstance(payload.get("profile"), dict) else payload
    profile = memory.canonicalize_profile(raw_profile)
    rec = db.upsert_user_marketing_memory(user["id"], profile)
    # Manual profile and auto-learned memory are independent layers: saving the
    # manual profile never touches the auto-learned evidence ledger.
    return _marketing_memory_payload(user["id"], rec["updated_at"])


@router.patch("/memory/marketing")
def update_marketing_memory_settings(request: Request, payload: dict = Body(...)) -> dict:
    user = auth.require_user(request)
    db.set_user_memory_enabled(user["id"], bool(payload.get("enabled")))
    rec = db.get_user_marketing_memory(user["id"])
    return _marketing_memory_payload(user["id"], (rec or {}).get("updated_at"))


@router.delete("/memory/marketing")
def clear_marketing_memory(request: Request) -> dict:
    user = auth.require_user(request)
    # Only clears the manual layer; auto-learned evidence is left untouched.
    db.delete_user_marketing_memory(user["id"])
    return _marketing_memory_payload(user["id"], None)


@router.get("/memory/marketing/evidence")
def get_marketing_memory_evidence(request: Request) -> dict:
    """Explainability: what the system has observed and whether it's promoted."""
    user = auth.require_user(request)
    threshold = memory.LONG_TERM_EVIDENCE_THRESHOLD
    items = []
    for row in db.list_user_marketing_memory_evidence(user["id"]):
        explicit = bool(row.get("explicit"))
        count = int(row.get("count") or 0)
        items.append({
            "field": row.get("field"),
            "value": row.get("value"),
            "count": count,
            "explicit": explicit,
            "promoted": count >= threshold,
            "first_seen_at": row.get("first_seen_at"),
            "last_seen_at": row.get("last_seen_at"),
        })
    return {"evidence": items, "threshold": threshold}


# ---------- clarification ----------

@router.post("/clarify")
def plan_clarification(request: Request, payload: dict = Body(...)) -> dict:
    """Decide whether/what to ask the user before running a task (LLM-driven)."""
    user = auth.require_user(request)
    prompt = str(payload.get("prompt") or "").strip()
    locale = "en" if str(payload.get("locale") or "zh").lower().startswith("en") else "zh"
    if not prompt:
        return {"needs_clarification": False, "questions": [], "source": "empty"}
    return clarify.plan_clarification(user["id"], prompt, locale)


# ---------- news ----------

import re as _re
from zoneinfo import ZoneInfo, available_timezones

_TIME_RE = _re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
_VALID_TZS = available_timezones()


def _validate_news_payload(payload: dict) -> dict:
    industry = str(payload.get("industry") or "").strip()
    if not industry:
        raise HTTPException(400, "行业/主题不能为空。")
    if len(industry) > 200:
        raise HTTPException(400, "行业/主题过长。")
    detail_level = str(payload.get("detail_level") or "brief").strip()
    if detail_level not in {"brief", "detailed"}:
        raise HTTPException(400, "内容细节取值不正确。")
    summary_time = str(payload.get("summary_time") or "").strip()
    if not _TIME_RE.match(summary_time):
        raise HTTPException(400, "总结时间格式应为 HH:MM。")
    timezone = str(payload.get("timezone") or "UTC").strip()
    if timezone not in _VALID_TZS:
        timezone = "UTC"
    language = str(payload.get("language") or "zh").strip().lower()
    if language not in {"zh", "en"}:
        language = "zh"
    return {
        "industry": industry,
        "detail_level": detail_level,
        "summary_time": summary_time,
        "timezone": timezone,
        "language": language,
        "enabled": bool(payload.get("enabled", True)),
    }


def _resolved_news_config(user_id: str) -> dict | None:
    """Fetch the user's news config, lazily reverting an expired cancellation.

    If a soft-cancelled config has passed its revert time, wipe both the config and
    the stored summaries so the panel shows the pre-activation empty state — even if
    the background scheduler has not yet run its cleanup tick. On the way out, attach
    ``revert_at`` for a still-cancelled config so the UI can reason about the window.
    """
    config = db.get_news_config(user_id)
    if config is None:
        return None
    if news.is_cancelled(config):
        if news.is_cancel_expired(config, time.time()):
            db.delete_news_data(user_id)
            return None
        config = {**config, "revert_at": news.cancellation_revert_ts(config)}
    return config


@router.get("/news/config")
def get_news_config(request: Request) -> dict:
    user = auth.require_user(request)
    return {"config": _resolved_news_config(user["id"])}


@router.put("/news/config")
def save_news_config(request: Request, payload: dict = Body(...)) -> dict:
    user = auth.require_user(request)
    fields = _validate_news_payload(payload)
    return {"config": db.upsert_news_config(user["id"], **fields)}


@router.delete("/news/config")
def remove_news_config(request: Request) -> dict:
    user = auth.require_user(request)
    db.delete_news_data(user["id"])
    return {"ok": True}


@router.post("/news/cancel")
def cancel_news(request: Request) -> dict:
    """Soft-cancel the auto-summary task.

    Stops the scheduler and stamps the cancel time, but keeps the last summary
    visible until the next day's summary time (see ``news.cancellation_revert_ts``).
    """
    user = auth.require_user(request)
    if db.get_news_config(user["id"]) is None:
        raise HTTPException(400, "尚未设置新闻总结任务。")
    config = db.cancel_news_config(user["id"], time.time())
    if config is None:
        raise HTTPException(404, "News task not found.")
    config = {**config, "revert_at": news.cancellation_revert_ts(config)}
    return {"config": config}


@router.get("/news/summary")
def get_news_summary(request: Request) -> dict:
    user = auth.require_user(request)
    # Trigger the shared expiry cleanup; after an expired revert the summaries are
    # wiped, so get_latest_news_summary naturally returns None.
    _resolved_news_config(user["id"])
    return {"summary": db.get_latest_news_summary(user["id"])}


@router.post("/news/refresh")
async def refresh_news(request: Request) -> dict:
    user = auth.require_user(request)
    config = _resolved_news_config(user["id"])
    if config is None:
        raise HTTPException(400, "请先设置新闻总结任务。")
    if news.is_cancelled(config):
        raise HTTPException(409, "自动总结任务已中断，请先设置新任务。")
    try:
        payload = await request.json()
    except Exception:  # noqa: BLE001 - remain compatible with older deployed clients
        payload = {}
    language = str(payload.get("language") or config.get("language") or "zh").lower()
    if language not in {"zh", "en"}:
        language = "zh"
    if language != config.get("language"):
        db.set_news_config_language(user["id"], language)
    config = {**config, "language": language}
    client = _client()
    try:
        record = await asyncio.to_thread(news.generate_summary, config, client)
    except news.NewsGenerationError as exc:
        raise HTTPException(502, str(exc)) from exc
    return {"summary": record}


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


_PREVIEW_CACHE_HEADERS = {"Cache-Control": "private, max-age=86400"}


@router.get("/uploads/{file_id}/preview")
def preview_upload(request: Request, file_id: str):
    """Inline-serve an uploaded file (optimized for images; PDFs pass through)."""
    user = auth.require_user(request)
    rec = db.get_upload(file_id, user["id"])
    if rec is None:
        raise HTTPException(404, "File not found.")
    path, media_type = image_serve.optimized_preview(rec["path"], f"upload_{file_id}")
    return FileResponse(path, media_type=media_type, headers=_PREVIEW_CACHE_HEADERS)


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
    path, media_type = image_serve.optimized_preview(rec["path"], f"artifact_{artifact_id}")
    return FileResponse(path, media_type=media_type, headers=_PREVIEW_CACHE_HEADERS)


@router.get("/artifacts/{artifact_id}")
def get_artifact_meta(request: Request, artifact_id: str) -> dict:
    user = auth.require_user(request)
    rec = db.get_artifact(artifact_id, user["id"])
    if rec is None:
        raise HTTPException(404, "Artifact not found.")
    # Don't leak filesystem path
    return {k: v for k, v in rec.items() if k != "path"}


# ---------- marketing image generation ----------

def _read_bytes(path_str: str) -> bytes:
    from pathlib import Path

    return Path(path_str).read_bytes()


def _resolve_image_source(user_id: str, source: dict | None) -> tuple[list[tuple[bytes, str]], str | None]:
    """Resolve a {type,id} source into reference image bytes + the source upload id.

    type 'upload' → an uploaded file (owner-checked); 'cutout' → an image_cutout artifact;
    'none' → no reference. Raises 404 (HTTPException) on a missing/cross-user id.
    """
    if not source or source.get("type") in (None, "none"):
        return [], None
    stype = source.get("type")
    sid = str(source.get("id") or "")
    if not sid:
        return [], None
    if stype == "upload":
        rec = db.get_upload(sid, user_id)
        if rec is None:
            raise HTTPException(404, "Source image not found.")
        return [(_read_bytes(rec["path"]), rec["mime"])], sid
    if stype == "cutout":
        rec = db.get_artifact(sid, user_id)
        if rec is None:
            raise HTTPException(404, "Cutout not found.")
        return [(_read_bytes(rec["path"]), rec["mime"] or "image/png")], None
    raise HTTPException(400, f"Unknown source type '{stype}'.")


@router.get("/image/skills")
def image_skills(request: Request) -> dict:
    auth.require_user(request)
    return {
        "skills": [
            {
                "id": s.key,
                "name": s.label,
                "description": s.description,
                "platform": s.key,
                "aspect_ratio": s.aspect_ratio,
            }
            for s in IMAGE_SKILLS.values()
        ]
    }


@router.post("/image/process")
async def image_process(request: Request, payload: dict = Body(...)) -> dict:
    user = auth.require_user(request)
    file_id = str(payload.get("file_id") or "")
    rec = db.get_upload(file_id, user["id"])
    if rec is None:
        raise HTTPException(404, "Uploaded file not found.")
    if not str(rec["mime"]).startswith("image/"):
        raise HTTPException(400, "Only image files can be processed.")
    image_bytes = _read_bytes(rec["path"])
    client = _client()
    out = await asyncio.to_thread(
        image_processing.process_upload, client, image_bytes, rec["mime"]
    )
    response: dict = {
        "classification": out["classification"],
        "original": {"file_id": file_id, "preview_url": f"/api/uploads/{file_id}/preview"},
        "cutout": None,
        "warning": out.get("warning"),
    }
    if out.get("cutout_png"):
        import uuid as _uuid
        from pathlib import Path

        from marketing_agent.tools.image_gen import ARTIFACTS_DIR

        ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
        cut_path = Path(ARTIFACTS_DIR) / f"{_uuid.uuid4().hex}_cutout.png"
        cut_path.write_bytes(out["cutout_png"])
        art = db.add_artifact(
            session_id=None,
            kind="image_cutout",
            filename="cutout.png",
            mime="image/png",
            path=str(cut_path.resolve()),
            user_id=user["id"],
        )
        response["cutout"] = {
            "artifact_id": art["id"],
            "preview_url": f"/api/artifacts/{art['id']}/preview",
        }
    return response


def _save_cutout_artifact(user_id: str, cutout_png: bytes) -> dict:
    import uuid as _uuid
    from pathlib import Path

    from marketing_agent.tools.image_gen import ARTIFACTS_DIR

    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    cut_path = Path(ARTIFACTS_DIR) / f"{_uuid.uuid4().hex}_cutout.png"
    cut_path.write_bytes(cutout_png)
    return db.add_artifact(
        session_id=None,
        kind="image_cutout",
        filename="cutout.png",
        mime="image/png",
        path=str(cut_path.resolve()),
        user_id=user_id,
    )


@router.post("/image/cutout")
async def image_cutout(request: Request, payload: dict = Body(...)) -> dict:
    """Remove the background from an uploaded image on demand (rembg only, no classify).

    Kept separate from generation so the panel can show the original instantly and only
    pay the (slower) cutout cost when the user clicks "remove background".
    """
    user = auth.require_user(request)
    file_id = str(payload.get("file_id") or "")
    rec = db.get_upload(file_id, user["id"])
    if rec is None:
        raise HTTPException(404, "Uploaded file not found.")
    if not str(rec["mime"]).startswith("image/"):
        raise HTTPException(400, "Only image files can have their background removed.")
    image_bytes = _read_bytes(rec["path"])
    try:
        cutout_png = await asyncio.to_thread(image_processing.cutout, image_bytes)
    except image_processing.CutoutUnavailable as exc:
        return {"artifact_id": None, "preview_url": None, "warning": str(exc)}
    art = _save_cutout_artifact(user["id"], cutout_png)
    return {
        "artifact_id": art["id"],
        "preview_url": f"/api/artifacts/{art['id']}/preview",
        "warning": None,
    }


def _run_generate(
    user_id: str,
    *,
    prompt: str,
    style_key: str | None,
    platform: str | None,
    reference_images: list[tuple[bytes, str]],
    source_upload_id: str | None,
    template_id: str | None,
    aspect_ratio: str | None,
    session_id: str | None,
    parent_history_id: str | None = None,
) -> dict:
    skill = select_image_skill(style_key, prompt, platform)
    effective_prompt = prompt
    effective_ratio = aspect_ratio
    if template_id:
        tpl = db.get_image_template(template_id)
        if tpl is None:
            raise HTTPException(404, "Template not found.")
        effective_prompt = f"{tpl['prompt']}\n\n{prompt}".strip()
        effective_ratio = aspect_ratio or tpl.get("aspect_ratio")

    result = image_gen.generate_image(
        effective_prompt,
        skill=skill,
        reference_images=reference_images,
        aspect_ratio=effective_ratio,
    )
    if not result.get("ok"):
        return {"ok": False, "unavailable": True, "message": result.get("message", "")}

    art = db.add_artifact(
        session_id=session_id,
        kind="image",
        filename=result["filename"],
        mime=result["mime"],
        path=result["path"],
        user_id=user_id,
    )
    params = {"aspect_ratio": effective_ratio, "template_id": template_id}
    if parent_history_id:
        params["parent_history_id"] = parent_history_id
    hist = db.add_image_history(
        user_id,
        prompt=prompt,
        style_key=skill.key,
        artifact_id=art["id"],
        source_upload_id=source_upload_id,
        params=params,
    )
    return {
        "ok": True,
        "artifact_id": art["id"],
        "history_id": hist["id"],
        "filename": art["filename"],
        "mime": art["mime"],
        "style_key": skill.key,
        "prompt": prompt,
        "created_at": hist["created_at"],
        "preview_url": f"/api/artifacts/{art['id']}/preview",
    }


@router.post("/image/generate")
async def image_generate(request: Request, payload: dict = Body(...)) -> dict:
    user = auth.require_user(request)
    prompt = str(payload.get("prompt") or "").strip()
    if not prompt:
        raise HTTPException(400, "描述不能为空。")
    reference_images, source_upload_id = _resolve_image_source(user["id"], payload.get("source"))
    return await asyncio.to_thread(
        _run_generate,
        user["id"],
        prompt=prompt,
        style_key=payload.get("style_key"),
        platform=payload.get("platform"),
        reference_images=reference_images,
        source_upload_id=source_upload_id,
        template_id=payload.get("template_id"),
        aspect_ratio=payload.get("aspect_ratio"),
        session_id=payload.get("session_id"),
    )


@router.post("/image/compose-save")
def image_compose_save(request: Request, payload: dict = Body(...)) -> dict:
    """Persist a client-composed template image (no AI) as an artifact + history row.

    The frontend renders the template composition on a canvas, uploads the result via
    /api/upload, and calls this to register it so it shows in preview + history.
    """
    user = auth.require_user(request)
    file_id = str(payload.get("file_id") or "")
    rec = db.get_upload(file_id, user["id"])
    if rec is None:
        raise HTTPException(404, "Composed image not found.")

    import shutil
    import uuid as _uuid
    from pathlib import Path

    from marketing_agent.tools.image_gen import ARTIFACTS_DIR

    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    style_key = str(payload.get("style_key") or "generic")
    dest = ARTIFACTS_DIR / f"{_uuid.uuid4().hex}_template_{style_key}.png"
    shutil.copyfile(rec["path"], dest)
    art = db.add_artifact(
        session_id=payload.get("session_id"),
        kind="image",
        filename=f"template_{style_key}.png",
        mime="image/png",
        path=str(dest.resolve()),
        user_id=user["id"],
    )
    prompt = str(payload.get("prompt") or "").strip() or "Template composition"
    hist = db.add_image_history(
        user["id"],
        prompt=prompt,
        style_key=style_key,
        artifact_id=art["id"],
        source_upload_id=file_id,
        params={"template_id": payload.get("template_id"), "composed": True},
    )
    return {
        "ok": True,
        "artifact_id": art["id"],
        "history_id": hist["id"],
        "filename": art["filename"],
        "mime": art["mime"],
        "style_key": style_key,
        "prompt": prompt,
        "created_at": hist["created_at"],
        "preview_url": f"/api/artifacts/{art['id']}/preview",
    }


@router.post("/image/re-edit")
async def image_reedit(request: Request, payload: dict = Body(...)) -> dict:
    user = auth.require_user(request)
    history_id = str(payload.get("history_id") or "")
    prompt = str(payload.get("prompt") or "").strip()
    if not prompt:
        raise HTTPException(400, "修改描述不能为空。")
    prev = db.get_image_history(history_id, user["id"])
    if prev is None:
        raise HTTPException(404, "History item not found.")
    if not prev.get("artifact_id"):
        raise HTTPException(400, "This history item has no image to edit.")
    art = db.get_artifact(prev["artifact_id"], user["id"])
    if art is None:
        raise HTTPException(404, "Source image not found.")
    reference_images = [(_read_bytes(art["path"]), art["mime"] or "image/png")]
    return await asyncio.to_thread(
        _run_generate,
        user["id"],
        prompt=prompt,
        style_key=payload.get("style_key") or prev.get("style_key"),
        platform=None,
        reference_images=reference_images,
        source_upload_id=prev.get("source_upload_id"),
        template_id=None,
        aspect_ratio=payload.get("aspect_ratio"),
        session_id=payload.get("session_id"),
        parent_history_id=history_id,
    )


def _history_view(rec: dict) -> dict:
    view = {
        "id": rec["id"],
        "prompt": rec["prompt"],
        "style_key": rec["style_key"],
        "artifact_id": rec["artifact_id"],
        "created_at": rec["created_at"],
        "params": rec.get("params", {}),
        "preview_url": None,
        "filename": None,
        "mime": None,
    }
    if rec.get("artifact_id"):
        view["preview_url"] = f"/api/artifacts/{rec['artifact_id']}/preview"
    return view


@router.get("/image/history")
def image_history(request: Request) -> dict:
    user = auth.require_user(request)
    return {"history": [_history_view(r) for r in db.list_image_history(user["id"])]}


@router.delete("/image/history/{history_id}")
def image_history_delete(request: Request, history_id: str) -> dict:
    user = auth.require_user(request)
    if not db.delete_image_history(history_id, user["id"]):
        raise HTTPException(404, "History item not found.")
    return {"deleted": history_id}


@router.get("/image/templates")
def image_templates(request: Request, platform: str | None = None, style: str | None = None) -> dict:
    auth.require_user(request)
    return {"templates": db.list_image_templates(platform, style)}


@router.get("/skills")
def content_workflow_skills(request: Request) -> dict:
    auth.require_user(request)
    return {"skills": marketing_skills.list_skills()}


def _attached_ids(file_ids: str | list[str] | None, csv_id: str | None = None) -> list[str]:
    ids: list[str] = []
    if isinstance(file_ids, str):
        ids.extend([fid for fid in file_ids.split(",") if fid.strip()])
    elif isinstance(file_ids, list):
        ids.extend([str(fid) for fid in file_ids if str(fid).strip()])
    if csv_id and csv_id not in ids:
        ids.append(csv_id)
    return ids


def _selected_skill_ids(skill_ids: str | list[str] | None) -> list[str]:
    return (
        [sid for sid in skill_ids.split(",") if sid.strip()]
        if isinstance(skill_ids, str)
        else [str(sid) for sid in (skill_ids or []) if str(sid).strip()]
    )


def _skill_notice(skill_ids: list[str]) -> str | None:
    names = marketing_skills.selected_skill_names(skill_ids)
    if not names:
        return None
    return "已使用 skill：" + "、".join(names)


def _output_language_for_prompt(prompt: str) -> str:
    lowered = prompt.lower()
    explicit_en = any(token in lowered for token in ("english", "in en", "write in en", "英文", "英语"))
    explicit_zh = any(token in lowered for token in ("chinese", "simplified chinese", "中文", "简体中文", "汉语"))
    if explicit_en and not explicit_zh:
        return "en"
    if explicit_zh and not explicit_en:
        return "zh"
    cjk = sum(1 for char in prompt if "\u4e00" <= char <= "\u9fff")
    letters = sum(1 for char in prompt if char.isalpha())
    return "zh" if cjk >= max(2, letters // 5) else "en"


def _build_user_message(
    user_id: str,
    prompt: str,
    file_ids: str | list[str] | None,
    csv_id: str | None = None,
    skill_ids: str | list[str] | None = None,
):
    extracted: list[dict] = []
    image_blocks: list[dict] = []

    # Data files are analyzed in the code-execution sandbox by the analytics agent,
    # so we never inline their contents — we only pass the path. This keeps large
    # datasets out of the prompt.
    data_exts = {".csv", ".xlsx", ".xls", ".json"}

    for fid in _attached_ids(file_ids, csv_id):
        rec = db.get_upload(fid, user_id)
        if rec is None:
            raise HTTPException(404, f"file_id '{fid}' not found.")
        from pathlib import Path
        path = Path(rec["path"])
        if path.suffix.lower() in data_exts:
            extracted.append({
                "kind": "text",
                "name": path.name,
                "text": f"(data file available at: {path})",
            })
            continue
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

    addendum = build_prompt_addendum(extracted) if extracted else ""
    selected_skills = _selected_skill_ids(skill_ids)
    output_language = _output_language_for_prompt(prompt)
    skill_addendum = marketing_skills.build_skill_addendum(selected_skills, output_language=output_language)
    if image_blocks:
        return [{"type": "text", "text": prompt + addendum + skill_addendum}, *image_blocks]
    return prompt + addendum + skill_addendum


def _persist_user_prompt(user_id: str, session_id: str, prompt: str) -> None:
    rows = db.list_messages(session_id)
    last = rows[-1] if rows else None
    if not last or last["role"] != "user" or last["content"] != prompt:
        db.add_message(session_id, "user", prompt)
    db.update_session(session_id, user_id=user_id, name=_derive_name(session_id, prompt), touch=True)
    # Long-term memory learning runs in the background (see _schedule_memory_update)
    # so LLM extraction never delays the model response.


def _pdf_sections_from_markdown(text: str, output_language: str = "en") -> list[dict]:
    sections: list[dict] = []
    current_heading = "摘要" if output_language == "zh" else "Summary"
    current_body: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            heading = stripped.lstrip("#").strip()
            if heading:
                if current_body:
                    sections.append({"heading": current_heading, "body": "\n".join(current_body).strip()})
                    current_body = []
                current_heading = heading
                continue
        current_body.append(line)
    if current_body:
        sections.append({"heading": current_heading, "body": "\n".join(current_body).strip()})
    fallback_heading = "摘要" if output_language == "zh" else "Summary"
    return sections or [{"heading": fallback_heading, "body": text}]


def _create_competitive_pdf_artifact(user_id: str, session_id: str, text: str, output_language: str = "en") -> dict:
    if output_language == "zh":
        title = "竞品分析报告"
        subtitle = "基于所选竞品分析 skill 生成"
        eyebrow = "企业营销交付物"
    else:
        title = "Competitive Positioning Brief"
        subtitle = "Generated from the selected competitive analysis skill."
        eyebrow = "Marketing Strategy Deliverable"
    payload = {
        "title": title,
        "subtitle": subtitle,
        "eyebrow": eyebrow,
        "sections": _pdf_sections_from_markdown(text, output_language=output_language),
    }
    rendered = generate_pdf(payload)
    return db.add_artifact(
        session_id=session_id,
        kind="pdf",
        filename=rendered["filename"],
        mime=rendered["mime"],
        path=rendered["path"],
        user_id=user_id,
    )


def _session_aware_on_event_factory(
    user_id: str,
    session_id: str,
    skill_notice: str | None = None,
    auto_competitive_pdf: bool = False,
    output_language: str = "en",
):
    accumulated_text: list[str] = []
    notice_emitted = False
    pdf_created = False

    def wrapper(inner_emit):
        def emit(event: str, payload: dict):
            nonlocal notice_emitted, pdf_created
            if event == "assistant_delta" and skill_notice and not notice_emitted:
                notice_emitted = True
                inner_emit("assistant_delta", {"delta": f"**{skill_notice}**\n\n"})
            if event == "assistant_delta":
                accumulated_text.append(str(payload.get("delta", "")))
            elif event == "result":
                final_text = str(payload.get("text", ""))
                if skill_notice and final_text and not final_text.startswith(f"**{skill_notice}**"):
                    final_text = f"**{skill_notice}**\n\n{final_text}"
                    payload = {**payload, "text": final_text}
                if auto_competitive_pdf and final_text and not pdf_created:
                    try:
                        rec = _create_competitive_pdf_artifact(user_id, session_id, final_text, output_language)
                        pdf_created = True
                        inner_emit(
                            "artifact_created",
                            {
                                "artifact_id": rec["id"],
                                "filename": rec["filename"],
                                "mime": rec["mime"],
                                "kind": rec["kind"],
                            },
                        )
                    except Exception as exc:  # noqa: BLE001
                        inner_emit("error", {"message": f"PDF generation failed: {exc}"})
                if final_text:
                    db.add_message(session_id, "assistant", final_text)
            elif event == "error":
                message = str(payload.get("message", "")).strip()
                if message:
                    db.add_message(session_id, "assistant", f"**Error:** {message}")
            elif event == "artifact_created":
                if str(payload.get("mime") or "") == "application/pdf":
                    pdf_created = True
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
    skill_ids: str | None = None,
):
    user = auth.require_user(request)
    conversation = sessions.prepare_for_turn(session_id, user["id"])
    if conversation is None:
        raise HTTPException(404, "Session not found.")
    if not prompt.strip():
        raise HTTPException(400, "Empty prompt.")

    selected_skills = _selected_skill_ids(skill_ids)
    output_language = _output_language_for_prompt(prompt)
    user_message = _build_user_message(user["id"], prompt, file_ids, csv_id, selected_skills)
    _persist_user_prompt(user["id"], session_id, prompt)
    _schedule_memory_update(user["id"], prompt)

    # Build user_message — string if no images, else list-of-blocks.
    client = _client()

    # Wrap the orchestrator's on_event to also persist assistant turns + bind artifacts to session.
    event_stream = orchestrator_event_stream(
        client,
        conversation,
        user_message,
        request=request,
        on_event_wrapper=_session_aware_on_event_factory(
            user["id"],
            session_id,
            skill_notice=_skill_notice(selected_skills),
            auto_competitive_pdf=marketing_skills.requires_pdf_deliverable(selected_skills),
            output_language=output_language,
        ),
    )
    return EventSourceResponse(to_sse(_with_current_user(user["id"], event_stream)))


@router.post("/sessions/{session_id}/complete")
async def complete_session(request: Request, session_id: str, payload: dict = Body(...)) -> dict:
    user = auth.require_user(request)
    conversation = sessions.prepare_for_turn(session_id, user["id"])
    if conversation is None:
        raise HTTPException(404, "Session not found.")
    prompt = str(payload.get("prompt") or "").strip()
    if not prompt:
        raise HTTPException(400, "Empty prompt.")

    selected_skills = _selected_skill_ids(payload.get("skill_ids"))
    output_language = _output_language_for_prompt(prompt)
    user_message = _build_user_message(
        user["id"],
        prompt,
        payload.get("file_ids"),
        payload.get("csv_id"),
        selected_skills,
    )
    _persist_user_prompt(user["id"], session_id, prompt)
    _schedule_memory_update(user["id"], prompt)
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

    recorder = _session_aware_on_event_factory(
        user["id"],
        session_id,
        skill_notice=_skill_notice(selected_skills),
        auto_competitive_pdf=marketing_skills.requires_pdf_deliverable(selected_skills),
        output_language=output_language,
    )(emit)
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


# ---------- organizations / directory ----------

def _org_member_public(row: dict) -> dict:
    return {
        "id": row["id"],
        "account": row.get("account"),
        "username": row.get("username"),
        "real_name": row.get("real_name"),
        "avatar": row.get("avatar"),
        "email": row.get("email"),
        "phone": row.get("phone"),
        "company": row.get("company"),
        "title": row.get("title"),
        "role": row.get("role"),
    }


@router.get("/org")
def org_get(request: Request) -> dict:
    user = auth.require_user(request)
    org = db.get_or_create_default_org(user["id"], user.get("username") or "")
    return {"org": org}


@router.post("/org")
def org_create(request: Request, payload: dict = Body(...)) -> dict:
    user = auth.require_user(request)
    name = (payload.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "组织名称不能为空。")
    if len(name) > 80:
        raise HTTPException(400, "组织名称不能超过 80 个字符。")
    db.create_org(user["id"], name)
    return {"org": db.get_current_org(user["id"])}


@router.post("/org/join")
def org_join(request: Request, payload: dict = Body(...)) -> dict:
    user = auth.require_user(request)
    code = (payload.get("invite_code") or "").strip()
    if not code:
        raise HTTPException(400, "请输入邀请码。")
    org = db.join_org_by_invite(user["id"], code)
    if org is None:
        raise HTTPException(404, "邀请码无效。")
    return {"org": org}


@router.post("/org/leave")
def org_leave(request: Request) -> dict:
    user = auth.require_user(request)
    org = db.get_current_org(user["id"])
    if org is None:
        raise HTTPException(400, "你还没有加入任何组织。")
    if org["owner_id"] == user["id"]:
        raise HTTPException(400, "组织所有者不能退出自己的组织。")
    db.remove_org_member(org["id"], user["id"])
    return {"org": db.get_or_create_default_org(user["id"], user.get("username") or "")}


@router.get("/org/members")
def org_members(request: Request) -> dict:
    user = auth.require_user(request)
    org = db.get_or_create_default_org(user["id"], user.get("username") or "")
    members = [_org_member_public(m) for m in db.list_org_members(org["id"])]
    return {"org": org, "members": members}


@router.post("/org/members")
def org_add_member(request: Request, payload: dict = Body(...)) -> dict:
    user = auth.require_user(request)
    org = db.get_or_create_default_org(user["id"], user.get("username") or "")
    account = (payload.get("account") or "").strip()
    if not account:
        raise HTTPException(400, "请输入对方账号（邮箱/手机号）。")
    target = db.get_user_by_account(auth.validate_account(account))
    if target is None:
        raise HTTPException(404, "未找到该注册用户。")
    if db.get_org_membership(org["id"], target["id"]) is not None:
        raise HTTPException(409, "对方已在该组织中。")
    db.add_org_member(org["id"], target["id"])
    return {"member": _org_member_public({**target, "role": "member"})}


@router.delete("/org/members/{member_id}")
def org_remove_member(request: Request, member_id: str) -> dict:
    user = auth.require_user(request)
    org = db.get_current_org(user["id"])
    if org is None:
        raise HTTPException(404, "组织不存在。")
    my = db.get_org_membership(org["id"], user["id"])
    if my is None:
        raise HTTPException(403, "你不在该组织中。")
    if member_id != user["id"] and my["role"] not in ("owner", "admin"):
        raise HTTPException(403, "只有管理员可以移除成员。")
    if member_id == org["owner_id"]:
        raise HTTPException(400, "不能移除组织所有者。")
    if not db.remove_org_member(org["id"], member_id):
        raise HTTPException(404, "成员不存在。")
    return {"removed": member_id}


# ---------- contacts ----------

def _external_contact_public(c: dict) -> dict:
    return {
        "id": c["id"],
        "contact_user_id": c.get("contact_user_id"),
        "name": c.get("name"),
        "phone": c.get("phone"),
        "email": c.get("email"),
        "company": c.get("company"),
        "title": c.get("title"),
        "avatar": c.get("avatar"),
        "starred": bool(c.get("starred")),
        "source": c.get("source"),
        "created_at": c.get("created_at"),
    }


@router.get("/contacts/external")
def contacts_external_list(request: Request) -> dict:
    user = auth.require_user(request)
    return {"contacts": [_external_contact_public(c) for c in db.list_external_contacts(user["id"])]}


@router.post("/contacts/external")
def contacts_external_add(request: Request, payload: dict = Body(...)) -> dict:
    user = auth.require_user(request)
    account = (payload.get("account") or "").strip()
    if account:
        target = db.get_user_by_account(auth.validate_account(account))
        if target is None:
            raise HTTPException(404, "未找到该注册用户，可改用手动填写。")
        if target["id"] == user["id"]:
            raise HTTPException(400, "不能添加自己为联系人。")
        if db.external_contact_with_user_exists(user["id"], target["id"]):
            raise HTTPException(409, "对方已在你的联系人中。")
        message = (payload.get("message") or "").strip() or None
        req = db.create_contact_request(user["id"], target["id"], message)
        return {"mode": "request", "request_id": req["id"]}
    name = (payload.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "请填写联系人名称或对方账号。")
    contact = db.create_external_contact(
        user["id"],
        name=name,
        phone=auth.validate_optional_text(payload.get("phone"), "手机号", max_len=20),
        email=auth.validate_optional_text(payload.get("email"), "邮箱", max_len=120),
        company=auth.validate_optional_text(payload.get("company"), "公司", max_len=120),
        title=auth.validate_optional_text(payload.get("title"), "职位", max_len=120),
        source="manual",
    )
    return {"mode": "manual", "contact": _external_contact_public(contact)}


@router.patch("/contacts/external/{contact_id}")
def contacts_external_update(request: Request, contact_id: str, payload: dict = Body(...)) -> dict:
    user = auth.require_user(request)
    fields: dict = {}
    for key in ("name", "phone", "email", "company", "title"):
        if key in payload:
            raw = payload[key]
            fields[key] = (str(raw).strip() or None) if raw is not None else None
    if "starred" in payload:
        fields["starred"] = bool(payload["starred"])
    if not fields:
        raise HTTPException(400, "没有可更新的字段。")
    if not db.update_external_contact(user["id"], contact_id, **fields):
        raise HTTPException(404, "联系人不存在。")
    return {"contact": _external_contact_public(db.get_external_contact(user["id"], contact_id))}


@router.delete("/contacts/external/{contact_id}")
def contacts_external_delete(request: Request, contact_id: str) -> dict:
    user = auth.require_user(request)
    if not db.delete_external_contact(user["id"], contact_id):
        raise HTTPException(404, "联系人不存在。")
    return {"deleted": contact_id}


@router.get("/contacts/requests")
def contacts_requests(request: Request) -> dict:
    user = auth.require_user(request)
    return {
        "incoming": db.list_incoming_contact_requests(user["id"]),
        "outgoing": db.list_outgoing_contact_requests(user["id"]),
    }


def _reciprocal_contact(owner: dict, other: dict) -> None:
    if not db.external_contact_with_user_exists(owner["id"], other["id"]):
        db.create_external_contact(
            owner["id"],
            name=other.get("username") or other.get("real_name") or "",
            email=other.get("email"),
            phone=other.get("phone"),
            company=other.get("company"),
            title=other.get("title"),
            avatar=other.get("avatar"),
            contact_user_id=other["id"],
            source="request",
        )


@router.post("/contacts/requests/{request_id}/accept")
def contacts_request_accept(request: Request, request_id: str) -> dict:
    user = auth.require_user(request)
    req = db.respond_contact_request(request_id, user["id"], "accepted")
    if req is None:
        raise HTTPException(404, "联系人申请不存在或已处理。")
    sender = db.get_user(req["from_user_id"])
    recipient = db.get_user(req["to_user_id"])
    if sender and recipient:
        _reciprocal_contact(recipient, sender)
        _reciprocal_contact(sender, recipient)
    return {"accepted": request_id}


@router.post("/contacts/requests/{request_id}/reject")
def contacts_request_reject(request: Request, request_id: str) -> dict:
    user = auth.require_user(request)
    req = db.respond_contact_request(request_id, user["id"], "rejected")
    if req is None:
        raise HTTPException(404, "联系人申请不存在或已处理。")
    return {"rejected": request_id}


@router.post("/contacts/star")
def contacts_star(request: Request, payload: dict = Body(...)) -> dict:
    user = auth.require_user(request)
    member_id = (payload.get("member_user_id") or "").strip()
    if not member_id:
        raise HTTPException(400, "缺少成员 ID。")
    db.star_member(user["id"], member_id)
    return {"starred": member_id}


@router.delete("/contacts/star/{member_user_id}")
def contacts_unstar(request: Request, member_user_id: str) -> dict:
    user = auth.require_user(request)
    db.unstar_member(user["id"], member_user_id)
    return {"unstarred": member_user_id}


@router.get("/contacts/starred")
def contacts_starred(request: Request) -> dict:
    user = auth.require_user(request)
    starred_ids = db.list_starred_member_ids(user["id"])
    members = [_org_member_public({**u, "role": None}) for u in db.get_users_by_ids(starred_ids)]
    externals = [
        _external_contact_public(c) for c in db.list_external_contacts(user["id"]) if c.get("starred")
    ]
    return {"members": members, "externals": externals}


# ---------- instant messaging (direct + group) ----------

def _one_conversation_for(user_id: str, conversation_id: str) -> dict | None:
    for conv in db.list_conversations_for_user(user_id):
        if conv["id"] == conversation_id:
            return conv
    return None


def _publish_conversation_update(conversation_id: str) -> None:
    for uid in db.list_conversation_member_ids(conversation_id):
        im_hub.publish(uid, {"event": "conversation_updated", "payload": {"conversation_id": conversation_id}})


@router.get("/conversations")
def conversations_list(request: Request, type: str | None = None) -> dict:
    user = auth.require_user(request)
    convs = db.list_conversations_for_user(user["id"])
    if type in ("direct", "group"):
        convs = [c for c in convs if c["type"] == type]
    return {"conversations": convs}


@router.post("/conversations")
async def conversations_create(request: Request, payload: dict = Body(...)) -> dict:
    user = auth.require_user(request)
    ctype = (payload.get("type") or "direct").strip()
    if ctype == "direct":
        peer_id = (payload.get("peer_id") or "").strip()
        if not peer_id:
            raise HTTPException(400, "缺少对方用户 ID。")
        if peer_id == user["id"]:
            raise HTTPException(400, "不能和自己创建会话。")
        if db.get_user(peer_id) is None:
            raise HTTPException(404, "对方用户不存在。")
        conv = db.find_or_create_direct_conversation(user["id"], peer_id)
    elif ctype == "group":
        member_ids = [str(x) for x in (payload.get("member_ids") or []) if str(x).strip()]
        member_ids = [m for m in member_ids if db.get_user(m) is not None and m != user["id"]]
        if not member_ids:
            raise HTTPException(400, "请选择至少一名群成员。")
        title = (payload.get("title") or "").strip() or "群聊"
        conv = db.create_group_conversation(user["id"], title, member_ids)
        _publish_conversation_update(conv["id"])
    else:
        raise HTTPException(400, "会话类型无效。")
    return {"conversation": _one_conversation_for(user["id"], conv["id"])}


@router.get("/conversations/{conversation_id}/messages")
def conversation_messages(
    request: Request, conversation_id: str, before: float | None = None, limit: int = 50
) -> dict:
    user = auth.require_user(request)
    if not db.is_conversation_member(conversation_id, user["id"]):
        raise HTTPException(404, "会话不存在。")
    return {"messages": db.list_im_messages(conversation_id, before, limit)}


@router.post("/conversations/{conversation_id}/messages")
async def conversation_send(request: Request, conversation_id: str, payload: dict = Body(...)) -> dict:
    user = auth.require_user(request)
    if not db.is_conversation_member(conversation_id, user["id"]):
        raise HTTPException(404, "会话不存在。")

    file_meta = payload.get("file")
    if isinstance(file_meta, dict) and file_meta.get("file_id"):
        # The sender just uploaded this file, so it is owner-checked here.
        rec = db.get_upload(str(file_meta["file_id"]), user["id"])
        if rec is None:
            raise HTTPException(400, "文件不存在或无权访问。")
        content = json.dumps(
            {
                "file_id": rec["id"],
                "name": rec["original_name"],
                "size": rec["size"],
                "mime": rec["mime"],
                "ext": rec["ext"],
            },
            ensure_ascii=False,
        )
        msg = db.add_im_message(conversation_id, user["id"], content, kind="file")
    else:
        content = (payload.get("content") or "").strip()
        if not content:
            raise HTTPException(400, "消息内容不能为空。")
        if len(content) > 4000:
            raise HTTPException(400, "消息内容过长。")
        msg = db.add_im_message(conversation_id, user["id"], content)

    event = {"event": "im_message", "payload": {**msg, "sender_name": user.get("username")}}
    for uid in db.list_conversation_member_ids(conversation_id):
        im_hub.publish(uid, event)
    return {"message": msg}


@router.post("/conversations/{conversation_id}/read")
def conversation_read(request: Request, conversation_id: str) -> dict:
    user = auth.require_user(request)
    if not db.is_conversation_member(conversation_id, user["id"]):
        raise HTTPException(404, "会话不存在。")
    read_at = time.time()
    db.mark_conversation_read(conversation_id, user["id"], read_at)
    # Notify the other members so their sent messages can flip to "read".
    payload = {"conversation_id": conversation_id, "user_id": user["id"], "last_read_at": read_at}
    for uid in db.list_conversation_member_ids(conversation_id):
        if uid != user["id"]:
            im_hub.publish(uid, {"event": "conversation_read", "payload": payload})
    return {"ok": True}


@router.get("/conversations/{conversation_id}/files/{file_id}/download")
def conversation_file_download(request: Request, conversation_id: str, file_id: str):
    user = auth.require_user(request)
    if not db.is_conversation_member(conversation_id, user["id"]):
        raise HTTPException(404, "会话不存在。")
    if not db.conversation_has_file(conversation_id, file_id):
        raise HTTPException(404, "文件不存在。")
    rec = db.get_upload_any(file_id)
    if rec is None:
        raise HTTPException(404, "文件不存在。")
    from pathlib import Path

    path = Path(rec["path"])
    return FileResponse(
        path,
        filename=path.name.split("_", 1)[-1] if "_" in path.name else path.name,
    )


@router.get("/conversations/{conversation_id}/members")
def conversation_members_list(request: Request, conversation_id: str) -> dict:
    user = auth.require_user(request)
    if not db.is_conversation_member(conversation_id, user["id"]):
        raise HTTPException(404, "会话不存在。")
    return {"members": [_org_member_public(m) for m in db.list_conversation_members(conversation_id)]}


@router.post("/conversations/{conversation_id}/members")
async def conversation_add_members(request: Request, conversation_id: str, payload: dict = Body(...)) -> dict:
    user = auth.require_user(request)
    if not db.is_conversation_member(conversation_id, user["id"]):
        raise HTTPException(404, "会话不存在。")
    conv = db.get_conversation(conversation_id)
    if not conv or conv.get("type") != "group":
        raise HTTPException(400, "只能给群聊添加成员。")

    candidates = [str(x) for x in (payload.get("member_ids") or []) if str(x).strip()]
    account = (payload.get("account") or "").strip()
    if account:
        target = db.get_user_by_account(auth.validate_account(account))
        if target is None:
            raise HTTPException(404, "未找到该注册用户。")
        candidates.append(target["id"])

    to_add = [
        uid
        for uid in dict.fromkeys(candidates)
        if db.get_user(uid) is not None and not db.is_conversation_member(conversation_id, uid)
    ]
    if not to_add:
        raise HTTPException(400, "没有可添加的新成员。")

    db.add_conversation_members(conversation_id, to_add)
    _publish_conversation_update(conversation_id)
    return {"members": [_org_member_public(m) for m in db.list_conversation_members(conversation_id)]}


@router.get("/im/stream")
async def im_stream(request: Request):
    user = auth.require_user(request)
    user_id = user["id"]

    async def event_gen() -> AsyncIterator[dict]:
        queue = im_hub.subscribe(user_id)
        try:
            yield {"event": "im_connected", "payload": {}}
            while True:
                if await request.is_disconnected():
                    return
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=HEARTBEAT_INTERVAL_SECONDS)
                except asyncio.TimeoutError:
                    yield {"event": "im_heartbeat", "payload": {}}
                    continue
                yield item
        finally:
            im_hub.unsubscribe(user_id, queue)

    return EventSourceResponse(to_sse(event_gen()))
