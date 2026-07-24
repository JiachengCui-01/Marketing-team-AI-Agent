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
        "name": "draft_approval",
        "description": (
            "Draft an office approval request (leave/请假, expense/报销, purchase/采购, "
            "or general) from the user's ask. Does NOT submit — prepares a draft the user "
            "confirms in the UI. Use for '帮我请3天年假', 'submit an expense claim', etc."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "type": {"type": "string", "enum": ["leave", "expense", "purchase", "general"]},
                "title": {"type": "string", "description": "Short title, e.g. '年假申请（3 天）'."},
                "fields": {
                    "type": "object",
                    "description": (
                        "Form fields in the user's language. leave: {leave_type, start_date, "
                        "end_date, days, reason}; expense: {amount, category, reason}."
                    ),
                    "additionalProperties": True,
                },
            },
            "required": ["type", "title", "fields"],
        },
    },
    {
        "name": "query_approvals",
        "description": "Look up approvals. scope='mine' = submitted by user; scope='pending' = awaiting user's action.",
        "input_schema": {
            "type": "object",
            "properties": {"scope": {"type": "string", "enum": ["mine", "pending"]}},
            "required": ["scope"],
        },
    },
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
            "Draft a calendar event / meeting. Does NOT save — prepares a draft the user confirms. "
            "Use for '约张三周四下午2点开会'. Compute absolute ISO datetimes from the current time "
            "given in the system prompt."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
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

_STATUS_ZH = {"pending": "待审批", "approved": "已通过", "rejected": "已驳回"}


def _status_zh(status: str) -> str:
    return _STATUS_ZH.get(status, status)


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

    def draft_approval(inp: dict) -> str:
        fields = inp.get("fields")
        draft = {
            "kind": "approval",
            "type": str(inp.get("type") or "general"),
            "title": (str(inp.get("title") or "审批申请").strip() or "审批申请"),
            "fields": fields if isinstance(fields, dict) else {},
        }
        _emit_draft(draft)
        return "已生成审批草稿并展示给用户确认。请一句话提醒用户核对卡片后点击“确认提交”，不要重复罗列字段。"

    def query_approvals(inp: dict) -> str:
        if not user_id:
            return "无法确定当前用户身份。"
        from server import db

        scope = str(inp.get("scope") or "mine")
        if scope == "pending":
            rows, label = db.list_approvals_pending_for(user_id), "待你审批"
        else:
            rows, label = db.list_approvals_created_by(user_id), "你发起"
        if not rows:
            return f"{label}的审批：暂无记录。"
        lines = [f"{label}的审批共 {len(rows)} 条："]
        lines += [f"- {r['title']}（{_status_zh(r['status'])}）" for r in rows[:10]]
        return "\n".join(lines)

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
            "end": str(inp.get("end") or ""),
            "location": str(inp.get("location") or ""),
            "attendees": [str(a) for a in attendees] if isinstance(attendees, list) else [],
        }
        _emit_draft(draft)
        return "已生成日程草稿并展示给用户确认。请一句话提醒用户核对时间后点击“确认创建”。"

    def query_calendar(_inp: dict) -> str:
        if not user_id:
            return "无法确定当前用户身份。"
        import time as _t

        from server import db

        rows = db.list_events(user_id, since=_t.time())
        if not rows:
            return "你近期没有日程安排。"
        lines = [f"你有 {len(rows)} 个即将到来的日程："]
        for r in rows[:10]:
            when = _t.strftime("%m-%d %H:%M", _t.localtime(r["start_at"]))
            lines.append(f"- {when} {r['title']}")
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
        "draft_approval": draft_approval,
        "query_approvals": query_approvals,
        "draft_task": draft_task,
        "query_tasks": query_tasks,
        "draft_event": draft_event,
        "query_calendar": query_calendar,
        "search_knowledge_base": search_knowledge_base,
    }
