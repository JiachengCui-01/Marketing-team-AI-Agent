"""OA copilot tool schemas + client-side handlers.

Human-in-the-loop safety: write actions (draft_*) never persist directly. They emit an
``oa_draft`` event (carrying a ``kind``) that the frontend renders as a confirmation card;
the user commits it via the matching ``POST`` endpoint. Read actions query the DB directly.

The handlers lazily import ``server.db`` so this module carries no import-time dependency
on the server package (the server imports the agent core, not the reverse).
"""
from __future__ import annotations

from typing import Callable

OA_TOOLS: list[dict] = [
    {
        "name": "draft_task",
        "description": (
            "Draft a task / to-do to create or assign to a colleague. Does NOT save — prepares "
            "a draft the user confirms. Use for '给张三派个任务…', '提醒我明天…', 'create a todo'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "detail": {"type": "string"},
                "priority": {"type": "string", "enum": ["low", "normal", "high"]},
                "assignee_name": {
                    "type": "string",
                    "description": "Colleague's name to assign to; omit to assign to the user.",
                },
                "due": {"type": "string", "description": "Human-readable due date/time, if given."},
            },
            "required": ["title"],
        },
    },
    {
        "name": "query_tasks",
        "description": "List the user's open tasks (assigned to or created by them).",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "draft_event",
        "description": (
            "Draft a calendar event / meeting to create or update. Does NOT save — prepares a draft "
            "the user confirms. For an update, first call query_calendar and pass the existing event_id. "
            "For a different/new event, omit event_id. Compute absolute ISO datetimes from the current "
            "time given in the system prompt."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "event_id": {
                    "type": "string",
                    "description": "Existing calendar event ID when modifying that event; omit for a new event.",
                },
                "title": {"type": "string"},
                "start": {"type": "string", "description": "ISO 8601 start datetime, e.g. 2026-07-30T14:00."},
                "end": {"type": "string", "description": "ISO 8601 end datetime (optional)."},
                "location": {"type": "string"},
                "attendees": {"type": "array", "items": {"type": "string"}, "description": "Attendee names."},
            },
            "required": ["title", "start"],
        },
    },
    {
        "name": "query_calendar",
        "description": "List the user's upcoming calendar events.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "search_knowledge_base",
        "description": (
            "Search the company knowledge base / documents and answer from the retrieved passages. "
            "Always cite the document titles you used."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    },
]

def build_oa_handlers(
    on_event: Callable[[str, dict], None] | None = None,
    user_id: str | None = None,
    history: list[dict] | None = None,
) -> dict[str, Callable[[dict], str]]:
    """Build client-side tool handlers bound to the current user + event bus.

    ``history`` is recent conversation turns ([{role, text}, ...]) used by the
    knowledge-base retrieval for coreference resolution.
    """

    def _emit_draft(draft: dict) -> None:
        if on_event:
            on_event("oa_draft", draft)

    def draft_task(inp: dict) -> str:
        draft = {
            "kind": "task",
            "title": (str(inp.get("title") or "任务").strip() or "任务"),
            "detail": str(inp.get("detail") or ""),
            "priority": str(inp.get("priority") or "normal"),
            "assignee_name": str(inp.get("assignee_name") or ""),
            "due": str(inp.get("due") or ""),
        }
        _emit_draft(draft)
        return "已生成任务草稿并展示给用户确认。请一句话提醒用户核对后点击“确认创建”。"

    def query_tasks(_inp: dict) -> str:
        if not user_id:
            return "无法确定当前用户身份。"
        from server import db

        rows = db.list_tasks(user_id, scope="all")
        open_rows = [r for r in rows if r["status"] == "open"]
        if not open_rows:
            return "你当前没有未完成的任务。"
        lines = [f"你有 {len(open_rows)} 个未完成任务："]
        lines += [f"- {r['title']}" for r in open_rows[:10]]
        return "\n".join(lines)

    def draft_event(inp: dict) -> str:
        attendees = inp.get("attendees")
        draft = {
            "kind": "calendar",
            "title": (str(inp.get("title") or "会议").strip() or "会议"),
            "start": str(inp.get("start") or ""),
        }
        event_id = str(inp.get("event_id") or "").strip()
        if event_id:
            draft["event_id"] = event_id
        if "end" in inp:
            draft["end"] = str(inp.get("end") or "")
        if "location" in inp:
            draft["location"] = str(inp.get("location") or "")
        if "attendees" in inp:
            draft["attendees"] = [str(a) for a in attendees] if isinstance(attendees, list) else []
        _emit_draft(draft)
        action = "更新" if event_id else "创建"
        return f"已生成日程{action}草稿并展示给用户确认。请一句话提醒用户核对后点击“确认{action}”。"

    def query_calendar(_inp: dict) -> str:
        if not user_id:
            return "无法确定当前用户身份。"
        import time as _t

        from server import db

        rows = db.list_events(user_id, since=_t.time())
        if not rows:
            return "你近期没有日程安排。"
        lines = [f"你有 {len(rows)} 个即将到来的日程（修改时把对应 ID 传给 draft_event.event_id）："]
        for r in rows[:10]:
            when = _t.strftime("%m-%d %H:%M", _t.localtime(r["start_at"]))
            location = f"，地点：{r['location']}" if r.get("location") else ""
            lines.append(f"- ID={r['id']}；{when} {r['title']}{location}")
        return "\n".join(lines)

    def search_knowledge_base(inp: dict) -> str:
        if not user_id:
            return "无法确定当前用户身份。"
        from server import db, kb_retrieval

        query = str(inp.get("query") or "").strip()
        if not query:
            return "请提供检索问题。"
        org = db.get_current_org(user_id)
        out = kb_retrieval.retrieve(
            org["id"] if org else None, query, history=history, limit=5, user_id=user_id
        )
        hits = out["results"]
        if not hits:
            return "知识库中没有找到相关内容。请提示用户先在“知识库”上传文档。"
        # Emit the cited documents so the UI can render source capsules (deduped by title).
        if on_event:
            seen: set[str] = set()
            sources = []
            for h in hits:
                if h["title"] not in seen:
                    seen.add(h["title"])
                    sources.append({"title": h["title"], "doc_id": h["doc_id"]})
            on_event("oa_sources", {"sources": sources})
        blocks = [f"[{h['title']}] {h['text'][:600]}" for h in hits]
        return "根据知识库检索到以下资料，请据此回答并标注引用的文档标题：\n\n" + "\n\n".join(blocks)

    return {
        "draft_task": draft_task,
        "query_tasks": query_tasks,
        "draft_event": draft_event,
        "query_calendar": query_calendar,
        "search_knowledge_base": search_knowledge_base,
    }
