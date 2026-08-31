"""Orchestrator — routes user requests to sub-agents and synthesizes results.

Streams text deltas via the on_event callback when the orchestrator produces its
final synthesized response, so the UI can render token-by-token.
"""
from __future__ import annotations

from typing import Callable

from . import llm_client
from .agents import analytics_agent, content_agent, research_agent
from .domain import BRAND, business_context_block
from .config import (
    MAX_TOOL_ROUNDS,
    MODEL_ID,
    ORCHESTRATOR_EFFORT,
    ORCHESTRATOR_MAX_TOKENS,
)
from .conversation import Conversation
from .source_scoring import annotate_markdown_with_source_tiers
from .tools.delegation_tools import DELEGATION_TOOLS

SYSTEM = f"""You are the head of marketing at {BRAND}. Your job is to understand the
request, decompose it into specialist tasks, dispatch those tasks to the right
specialists, and synthesize their output into a single clean deliverable.

{business_context_block()}

You have three specialists, accessible only via the delegate_* tools:

- delegate_to_content_agent — for any customer-facing copy: marketplace listings
  (Amazon, Wayfair), our own product pages, social posts and video scripts, email,
  ads, blog guides. It can also produce PDF deliverables such as a spec sheet,
  category catalog page, or competitor comparison.
- delegate_to_analytics_agent — for any sales/advertising/returns data analysis:
  ACOS, conversion rate, AOV, return rate, margin after landed cost, inventory turns.
- delegate_to_research_agent — for any external information: US furniture demand and
  category trends, competitor listings and pricing, marketplace policy, tariffs and
  duties, product-safety rules.

Hard rules:

1. NEVER write customer-facing copy yourself. Always delegate to the content agent.
2. NEVER compute metrics or interpret data files yourself. Always delegate to analytics.
3. NEVER claim external facts without delegating to research.
4. NEVER state a specific dimension, material, weight capacity, assembly time,
   delivery window, or certification that did not come from the user, an attached
   file, or a cited source. Pass along what you were given; where a figure is
   missing, keep the specialist's [confirm ...] placeholder in the final answer
   rather than filling it in.
5. When multiple specialists are needed, prefer parallel dispatch (multiple tool_use
   blocks in one response) when tasks are independent.
6. After all specialists return, write a final synthesized response in well-formatted
   markdown.
7. If a request clearly fits one specialist, just delegate to that one.
8. If a specialist returns an unavailable/error result, do not retry it.
9. When the user asks to generate/create/make a PDF or other file deliverable,
   delegate to the content agent immediately. If product, audience, or tone details
   are missing, make reasonable assumptions in the specialist task instead of asking
   a clarification question first — but never assume a physical spec.
10. If your previous assistant message asked a clarification question and the latest
    user message answers it, merge that answer into the original task and execute the
    task. Do not ask the same clarification again.
11. When synthesizing research specialist output, preserve inline citation links at
    the end of factual sentences or bullets. Do not drop the specialist's source
    URLs or Source Credibility notes; the UI depends on those URLs to render source
    capsules and source-tier risk labels.

Be decisive. Don't ask clarifying questions unless the request is genuinely ambiguous.
"""


def _dispatch(client: llm_client.DeepSeek, name: str, payload: dict, on_event=None) -> str:
    # Specialists reuse the orchestrator's client: it is stateless per call and its
    # underlying HTTP connection pool is thread-safe, so per-dispatch clients would
    # only add TLS handshakes.
    if name == "delegate_to_content_agent":
        return content_agent.run(client, on_event=on_event, **payload)
    if name == "delegate_to_analytics_agent":
        return analytics_agent.run(client, **payload)
    if name == "delegate_to_research_agent":
        return research_agent.run(client, **payload)
    return f"Error: unknown specialist '{name}'."


def _task_text(payload: dict) -> str:
    task = payload.get("task") or payload.get("brief") or payload.get("query") or payload.get("prompt")
    if isinstance(task, str) and task.strip():
        return task.strip()
    return "Review the request and complete the assigned specialist work."


def _specialist_method(name: str) -> str:
    if name == "delegate_to_content_agent":
        return (
            "Apply the channel SOP to turn the brief into publish-ready copy — listing, "
            "product page, social, email, or a shareable deliverable."
        )
    if name == "delegate_to_analytics_agent":
        return (
            "Run pandas over the supplied data, compute the sales/ad/returns metrics "
            "requested, and summarize decision-useful findings."
        )
    if name == "delegate_to_research_agent":
        return (
            "Gather evidence on the US furniture market, competing listings, or policy "
            "changes; check source quality and preserve citations for synthesis."
        )
    return "Complete the assigned specialist task and return concise findings."


def run_orchestrator(
    client: llm_client.DeepSeek,
    conversation: Conversation,
    user_message,
    on_event: Callable[[str, dict], None] | None = None,
) -> str:
    """Process one user turn end-to-end. Mutates ``conversation`` with new messages.

    ``user_message`` may be a plain string or a list of content blocks (for image/file
    attachments).
    """
    conversation.messages.append({"role": "user", "content": user_message})
    failed_specialists: set[str] = set()
    research_contexts: list[str] = []
    if on_event:
        on_event(
            "orchestrator_step",
            {
                "stage": "intake",
                "title": "理解任务",
                "detail": "读取用户请求、附件和已选 skill，判断需要哪些专家能力参与。",
                "status": "running",
            },
        )

    for round_index in range(MAX_TOOL_ROUNDS):
        if on_event:
            on_event(
                "orchestrator_step",
                {
                    "stage": "planning",
                    "title": "规划下一步",
                    "detail": "根据当前上下文决定是继续分派专家、等待专家结果，还是开始汇总最终答案。",
                    "status": "running",
                    "round": round_index + 1,
                },
            )
        response = client.messages.create(
            model=MODEL_ID,
            max_tokens=ORCHESTRATOR_MAX_TOKENS,
            system=SYSTEM,
            thinking={"type": "adaptive"},
            output_config={"effort": ORCHESTRATOR_EFFORT},
            tools=DELEGATION_TOOLS,
            messages=conversation.messages,
        )

        conversation.add_assistant(response.content)

        if on_event:
            on_event(
                "orchestrator_response",
                {
                    "stop_reason": response.stop_reason,
                    "usage": {
                        "input_tokens": response.usage.input_tokens,
                        "output_tokens": response.usage.output_tokens,
                    },
                },
            )

        if response.stop_reason == "end_turn":
            if on_event:
                on_event(
                    "orchestrator_step",
                    {
                        "stage": "synthesis",
                        "title": "汇总最终答案",
                        "detail": "整合专家结论、补充必要说明，并将内容整理成可读的最终回复。",
                        "status": "running",
                    },
                )
            final_text = _finalize_text(_final_text(response.content), research_contexts)
            # Stream deltas of the already-completed text so the UI sees typewriter output.
            if on_event:
                _stream_text(on_event, final_text)
                on_event(
                    "orchestrator_step",
                    {
                        "stage": "synthesis",
                        "title": "答案汇总完成",
                        "detail": "最终回复已完成整理，正在展示给用户。",
                        "status": "done",
                    },
                )
                on_event("result", {"text": final_text})
            return final_text

        if response.stop_reason == "pause_turn":
            continue

        if response.stop_reason == "tool_use":
            tool_results = []
            unavailable_results = []
            tool_blocks = [block for block in response.content if block.type == "tool_use"]
            if on_event and tool_blocks:
                on_event(
                    "orchestrator_step",
                    {
                        "stage": "dispatch",
                        "title": "分派专家任务",
                        "detail": f"识别到 {len(tool_blocks)} 个专家任务，开始按能力边界分派执行。",
                        "status": "running",
                    },
                )
            for block in response.content:
                if block.type != "tool_use":
                    continue
                if block.name in failed_specialists:
                    result = (
                        f"## Specialist Unavailable\n\n{block.name} already returned an "
                        "unavailable/error result for this request."
                    )
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result,
                    })
                    continue
                if on_event:
                    on_event(
                        "specialist_start",
                        {
                            "specialist": block.name,
                            "task": _task_text(block.input),
                            "method": _specialist_method(block.name),
                        },
                    )
                    on_event("delegating", {"specialist": block.name, "input": block.input})
                try:
                    result = _dispatch(client, block.name, block.input, on_event=on_event)
                    if block.name == "delegate_to_research_agent":
                        research_contexts.append(result)
                    if _is_unavailable_result(result):
                        failed_specialists.add(block.name)
                        unavailable_results.append(result)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result,
                    })
                    if on_event:
                        on_event("specialist_done", {"specialist": block.name, "chars": len(result)})
                except Exception as exc:  # noqa: BLE001
                    failed_specialists.add(block.name)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": f"Specialist '{block.name}' failed: {exc}",
                        "is_error": True,
                    })
                    if on_event:
                        on_event("specialist_error", {"specialist": block.name, "error": str(exc)})

            conversation.add_tool_results(tool_results)
            if unavailable_results and len(tool_results) == len(unavailable_results):
                final_text = "\n\n".join(unavailable_results)
                if on_event:
                    on_event(
                        "orchestrator_step",
                        {
                            "stage": "synthesis",
                            "title": "整理不可用结果",
                            "detail": "所有专家均返回不可用或错误信息，正在将可解释的失败原因反馈给用户。",
                            "status": "running",
                        },
                    )
                    _stream_text(on_event, final_text)
                    on_event(
                        "orchestrator_step",
                        {
                            "stage": "synthesis",
                            "title": "反馈已完成",
                            "detail": "已完成异常结果整理。",
                            "status": "done",
                        },
                    )
                    on_event("result", {"text": final_text})
                return final_text
            if on_event:
                on_event(
                    "orchestrator_step",
                    {
                        "stage": "review",
                        "title": "检查专家结果",
                        "detail": "专家结果已返回，正在判断是否需要继续分派或进入最终汇总。",
                        "status": "done",
                    },
                )
            continue

        if on_event:
            on_event(
                "orchestrator_step",
                {
                    "stage": "synthesis",
                    "title": "汇总最终答案",
                    "detail": "根据已获得的信息生成最终回复，并保留必要的引用和交付物说明。",
                    "status": "running",
                },
            )
        final = _finalize_text(_final_text(response.content), research_contexts)
        if on_event:
            _stream_text(on_event, final)
            on_event(
                "orchestrator_step",
                {
                    "stage": "synthesis",
                    "title": "答案汇总完成",
                    "detail": "最终回复已完成整理，正在展示给用户。",
                    "status": "done",
                },
            )
            on_event("result", {"text": final})
        return final

    return "[Orchestrator stopped: exceeded MAX_TOOL_ROUNDS.]"


def _stream_text(on_event: Callable[[str, dict], None], text: str, chunk: int = 24) -> None:
    """Emit text in small chunks so the frontend renders a typewriter effect.

    The model call itself is non-streaming (we need stop_reason / tool_use semantics),
    so we replay the final text in deltas on the SSE bus. Chunk size of ~24 chars
    keeps UI feel snappy without per-character event overhead.
    """
    if not text:
        return
    for i in range(0, len(text), chunk):
        on_event("assistant_delta", {"delta": text[i : i + chunk]})


def _final_text(content: list) -> str:
    return "\n".join(b.text for b in content if b.type == "text").strip()


def _finalize_text(text: str, research_contexts: list[str]) -> str:
    if not research_contexts:
        return text
    return annotate_markdown_with_source_tiers(
        text,
        language=_language_for_text(text),
        fallback_source_text="\n\n".join(research_contexts),
        ensure_inline_citations=True,
    )


def _language_for_text(text: str) -> str:
    cjk = sum(1 for char in text if "\u4e00" <= char <= "\u9fff")
    letters = sum(1 for char in text if char.isalpha())
    return "zh" if cjk >= max(4, letters // 5) else "en"


def _is_unavailable_result(text: str) -> bool:
    lowered = text.lower()
    return (
        "## research unavailable" in lowered
        or "## specialist unavailable" in lowered
        or "error:" in lowered
        or "unavailable" in lowered
    )
