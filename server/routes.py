"""API routes."""
from __future__ import annotations

import asyncio
import os
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

from . import auth, db, image_processing, image_serve, marketing_skills, news, sessions, uploads
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
    conversation = sessions.get(session_id, user["id"])
    if conversation is None:
        raise HTTPException(404, "Session not found.")
    if not prompt.strip():
        raise HTTPException(400, "Empty prompt.")

    selected_skills = _selected_skill_ids(skill_ids)
    output_language = _output_language_for_prompt(prompt)
    user_message = _build_user_message(user["id"], prompt, file_ids, csv_id, selected_skills)
    _persist_user_prompt(user["id"], session_id, prompt)

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
    conversation = sessions.get(session_id, user["id"])
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
