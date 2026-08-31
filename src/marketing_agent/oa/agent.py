"""OA copilot turn loop.

Mirrors ``orchestrator.run_orchestrator``: a non-streaming tool-use loop that replays
the final text as ``assistant_delta`` chunks over the SSE bus. It exposes the OA tools
(approvals, etc.) plus the retained marketing delegation tools, so the copilot can both
run office workflows and fall back to the existing content/analytics/research specialists.
"""
from __future__ import annotations

import time
from typing import Any, Callable

from .. import llm_client
from ..config import MAX_TOOL_ROUNDS, MODEL_ID, ORCHESTRATOR_EFFORT, ORCHESTRATOR_MAX_TOKENS
from ..conversation import Conversation
from ..domain import BRAND
from ..orchestrator import _dispatch, _final_text, _stream_text, _task_text
from ..tools.delegation_tools import DELEGATION_TOOLS
from .tools import OA_TOOLS, build_oa_handlers

# Friendly Agent-Trace labels for each OA tool so users can see what the workspace did.
_TOOL_STEPS: dict[str, tuple[str, str]] = {
    "draft_approval": ("起草审批", "根据你的请求生成审批草稿，待你确认后提交。"),
    "query_approvals": ("查询审批", "读取你发起或待你审批的记录。"),
    "draft_task": ("起草任务", "生成任务草稿，待你确认后创建。"),
    "query_tasks": ("查询任务", "读取你的未完成待办。"),
    "draft_event": ("起草日程", "生成日程草稿，待你确认后创建。"),
    "query_calendar": ("查询日程", "读取你即将到来的日程。"),
    "search_knowledge_base": ("检索知识库", "在你有权限的知识库中检索相关资料并据此作答。"),
}

SYSTEM_TEMPLATE = """你是 {brand} 的企业 AI 工作助手。{brand} 是一家设计驱动的大件家具品牌：自主设计沙发、床架、餐桌椅、储物柜等大件家具，交由供应商代工生产，出口并以 DTC 方式直接卖给美国消费者。销售渠道包括 Amazon、Wayfair、自有独立站，以及 Instagram、Pinterest、TikTok、EDM 等。

你既处理公司内部的日常办公事务，也调度营销专家完成对外的内容、数据和市场研究工作。

当前时间：{now}（用于计算日程/审批中的相对日期，如「下周一」「明天下午」）。团队与美国市场存在时差，凡涉及美国客户、平台节点或供应链交期的时间安排，提醒用户确认时区。

可用能力：
- 审批：draft_approval（起草请假/报销/采购/用章等审批单）、query_approvals（查询我发起的 / 待我审批）。
- 任务：draft_task（创建或指派待办）、query_tasks（查询我的未完成任务）。
- 日程：draft_event（预约会议/日程，start/end 用 ISO 8601 绝对时间）、query_calendar（查询即将到来的日程）。
- 知识库：search_knowledge_base（检索公司文档并据此回答，需标注引用的文档标题）。公司知识库里通常有产品规格书、供应商与打样资料、平台规则、物流与关税说明。
- 营销专家：delegate_to_content_agent（listing / 商详 / 社媒 / 短视频脚本 / 邮件 / 广告 / 博客 / PDF 交付物）、delegate_to_analytics_agent（销售、广告、退货数据）、delegate_to_research_agent（美国家具市场、竞品 listing、平台政策、关税与合规）。

硬性规则：
1. 所有"写"操作（draft_approval / draft_task / draft_event）都只生成草稿，绝不能声称"已提交/已创建"——必须由用户在界面确认草稿卡片后才真正生效。draft 之后用一句话提示用户核对并确认，不要重复罗列所有字段。
2. 查询类请求调用对应的 query_* 工具；知识库问答调用 search_knowledge_base，并基于返回的资料作答、标注文档标题。
3. 文案/listing/数据/市场研究类请求，委派给对应的 delegate_* 专家，不要自己写文案、自己算指标，也不要凭印象断言外部事实。
4. 尺寸、材质、承重、组装时间、配送时效、认证、保修等实物参数，只能来自用户输入、附件或知识库检索结果。缺失时保留「[待确认 尺寸]」这类占位，绝不猜一个看起来合理的数字——写错一个尺寸就是一次退货加一条差评。
5. 汇总市场研究专家的结果时，必须原样保留正文里的行内引用链接（[标题](url)）和来源可信度说明。界面依赖这些 URL 渲染来源胶囊和分级标签，删掉链接等于把"可溯源"变成"凭空断言"。
6. 使用用户所用的语言回复（默认简体中文），保持简洁、果断，不要过度追问；非实物类信息缺失时做合理假设并说明。
7. 若某能力返回不可用或无结果，简要说明即可。
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
    client: llm_client.DeepSeek,
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
    system = SYSTEM_TEMPLATE.format(
        brand=BRAND, now=time.strftime("%Y-%m-%d %H:%M %A", time.localtime())
    )

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
                    if on_event and block.name in _TOOL_STEPS:
                        title, detail = _TOOL_STEPS[block.name]
                        on_event(
                            "orchestrator_step",
                            {"stage": "tool", "title": title, "detail": detail, "status": "running"},
                        )
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
