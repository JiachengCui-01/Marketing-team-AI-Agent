"""OA copilot turn loop.

Mirrors ``orchestrator.run_orchestrator``: a non-streaming tool-use loop that replays
the final text as ``assistant_delta`` chunks over the SSE bus. It exposes the OA tools
(approvals, etc.) plus the retained marketing delegation tools, so the copilot can both
run office workflows and fall back to the existing content/analytics/research specialists.
"""
from __future__ import annotations

import time
from typing import Any, Callable

import anthropic

from ..config import MAX_TOOL_ROUNDS, MODEL_ID, ORCHESTRATOR_EFFORT, ORCHESTRATOR_MAX_TOKENS
from ..conversation import Conversation
from ..orchestrator import _dispatch, _final_text, _stream_text, _task_text
from ..tools.delegation_tools import DELEGATION_TOOLS
from .tools import OA_TOOLS, build_oa_handlers

SYSTEM_TEMPLATE = """你是一个企业 OA（办公自动化）智能助手，服务于企业员工的日常办公。你可以通过工具完成办公事务，也可以调用营销专家能力。

当前时间：{now}（用于计算日程/审批中的相对日期，如“下周一”“明天下午”）。

可用能力：
- 审批：draft_approval（起草请假/报销/采购/用章等审批单）、query_approvals（查询我发起的 / 待我审批）。
- 任务：draft_task（创建或指派待办）、query_tasks（查询我的未完成任务）。
- 日程：draft_event（预约会议/日程，start/end 用 ISO 8601 绝对时间）、query_calendar（查询即将到来的日程）。
- 知识库：search_knowledge_base（检索公司文档并据此回答，需标注引用的文档标题）。
- 营销（保留的原有能力）：delegate_to_content_agent / delegate_to_analytics_agent / delegate_to_research_agent。

硬性规则：
1. 所有“写”操作（draft_approval / draft_task / draft_event）都只生成草稿，绝不能声称“已提交/已创建”——必须由用户在界面确认草稿卡片后才真正生效。draft 之后用一句话提示用户核对并确认，不要重复罗列所有字段。
2. 查询类请求调用对应的 query_* 工具；知识库问答调用 search_knowledge_base，并基于返回的资料作答、标注文档标题。
3. 营销/文案/数据/研究类请求，委派给对应的 delegate_* 专家。
4. 使用用户所用的语言回复（默认简体中文），保持简洁、果断，不要过度追问；信息缺失时做合理假设。
5. 若某能力返回不可用或无结果，简要说明即可。
"""


def _history_from(conversation: Conversation) -> list[dict]:
    """Extract prior (role, text) turns for coreference-aware KB retrieval."""
    out: list[dict] = []
    for msg in conversation.messages:
        content = msg.get("content")
        if isinstance(content, str):
            text = content
        elif isinstance(content, list):
            text = " ".join(
                getattr(b, "text", "") if not isinstance(b, dict) else str(b.get("text", ""))
                for b in content
            ).strip()
        else:
            text = ""
        if text:
            out.append({"role": msg.get("role", "user"), "text": text})
    return out


def run_oa_copilot(
    client: anthropic.Anthropic,
    conversation: Conversation,
    user_message: Any,
    on_event: Callable[[str, dict], None] | None = None,
    *,
    user_id: str | None = None,
) -> str:
    """Process one OA copilot turn end-to-end, mutating ``conversation``."""
    history = _history_from(conversation)
    conversation.messages.append({"role": "user", "content": user_message})
    handlers = build_oa_handlers(on_event=on_event, user_id=user_id, history=history)
    tools = [*OA_TOOLS, *DELEGATION_TOOLS]
    system = SYSTEM_TEMPLATE.format(now=time.strftime("%Y-%m-%d %H:%M %A", time.localtime()))

    if on_event:
        on_event(
            "orchestrator_step",
            {
                "stage": "intake",
                "title": "理解任务",
                "detail": "读取你的请求，判断需要办公能力（审批/任务/日程/知识库）还是营销专家。",
                "status": "running",
            },
        )

    for _ in range(MAX_TOOL_ROUNDS):
        response = client.messages.create(
            model=MODEL_ID,
            max_tokens=ORCHESTRATOR_MAX_TOKENS,
            system=system,
            thinking={"type": "adaptive"},
            output_config={"effort": ORCHESTRATOR_EFFORT},
            tools=tools,
            messages=conversation.messages,
        )
        conversation.add_assistant(response.content)
        stop = response.stop_reason

        if stop in ("end_turn", "refusal", "max_tokens", None):
            final = _final_text(response.content)
            if stop == "refusal" and not final:
                final = "（助手拒绝了本次请求。）"
            if on_event:
                on_event(
                    "orchestrator_step",
                    {"stage": "synthesis", "title": "汇总回复", "detail": "整理结果并生成最终回复。", "status": "done"},
                )
                _stream_text(on_event, final)
                on_event("result", {"text": final})
            return final

        if stop == "pause_turn":
            continue

        if stop == "tool_use":
            tool_results: list[dict] = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                if block.name in handlers:
                    try:
                        result = handlers[block.name](block.input)
                    except Exception as exc:  # noqa: BLE001
                        result = f"工具执行失败：{exc}"
                    tool_results.append(
                        {"type": "tool_result", "tool_use_id": block.id, "content": result}
                    )
                elif block.name.startswith("delegate_"):
                    if on_event:
                        on_event(
                            "specialist_start",
                            {"specialist": block.name, "task": _task_text(block.input), "method": ""},
                        )
                    try:
                        result = _dispatch(client, block.name, block.input, on_event=on_event)
                    except Exception as exc:  # noqa: BLE001
                        result = f"专家调用失败：{exc}"
                    if on_event:
                        on_event("specialist_done", {"specialist": block.name, "chars": len(result)})
                    tool_results.append(
                        {"type": "tool_result", "tool_use_id": block.id, "content": result}
                    )
                else:
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": f"Error: no handler for tool '{block.name}'.",
                            "is_error": True,
                        }
                    )
            if not tool_results:
                continue
            conversation.add_tool_results(tool_results)
            continue

        # Fallback for any unhandled stop reason.
        final = _final_text(response.content)
        if on_event:
            _stream_text(on_event, final)
            on_event("result", {"text": final})
        return final

    fallback = "[OA Copilot 超过最大工具轮次。]"
    if on_event:
        on_event("result", {"text": fallback})
    return fallback
