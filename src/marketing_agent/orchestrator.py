"""Orchestrator — routes user requests to sub-agents and synthesizes results.

Streams text deltas via the on_event callback when the orchestrator produces its
final synthesized response, so the UI can render token-by-token.
"""
from __future__ import annotations

from typing import Callable

import anthropic

from .agents import analytics_agent, content_agent, research_agent
from .config import (
    MAX_TOOL_ROUNDS,
    MODEL_ID,
    ORCHESTRATOR_EFFORT,
    ORCHESTRATOR_MAX_TOKENS,
)
from .conversation import Conversation
from .source_scoring import annotate_markdown_with_source_tiers
from .tools.delegation_tools import DELEGATION_TOOLS

SYSTEM = """You are the chief of staff for an enterprise marketing team. Your job is to
understand the user's request, decompose it into specialist tasks, dispatch those tasks
to the right specialists, and synthesize their output into a single clean deliverable.

You have three specialists, accessible only via the delegate_* tools:

- delegate_to_content_agent — for any copywriting (social, blog, email, ads). The
  content agent can also produce PDF deliverables when the user asks for one.
- delegate_to_analytics_agent — for any CSV/data/KPI/performance analysis
- delegate_to_research_agent — for any external/market/competitor/trend research

Hard rules:

1. NEVER write marketing copy yourself. Always delegate to the content agent.
2. NEVER compute metrics or interpret CSVs yourself. Always delegate to analytics.
3. NEVER claim external facts without delegating to research.
4. When multiple specialists are needed, prefer parallel dispatch (multiple tool_use
   blocks in one response) when tasks are independent.
5. After all specialists return, write a final synthesized response in well-formatted
   markdown.
6. If a request clearly fits one specialist, just delegate to that one.
7. If a specialist returns an unavailable/error result, do not retry it.
8. When the user asks to generate/create/make a PDF or other file deliverable,
   delegate to the content agent immediately. If product, audience, or tone details
   are missing, make reasonable assumptions in the specialist task instead of asking
   a clarification question first.
9. If your previous assistant message asked a clarification question and the latest
   user message answers it, merge that answer into the original task and execute the
   task. Do not ask the same clarification again.
10. When synthesizing research specialist output, preserve inline citation links at
    the end of factual sentences or bullets. Do not drop the specialist's source
    URLs or Source Credibility notes; the UI depends on those URLs to render source
    capsules and source-tier risk labels.

Be decisive. Don't ask clarifying questions unless the request is genuinely ambiguous.
"""


def _dispatch(client: anthropic.Anthropic, name: str, payload: dict, on_event=None) -> str:
    specialist_client = anthropic.Anthropic()
    if name == "delegate_to_content_agent":
        return content_agent.run(specialist_client, on_event=on_event, **payload)
    if name == "delegate_to_analytics_agent":
        return analytics_agent.run(specialist_client, **payload)
    if name == "delegate_to_research_agent":
        return research_agent.run(specialist_client, **payload)
    return f"Error: unknown specialist '{name}'."


def run_orchestrator(
    client: anthropic.Anthropic,
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

    for _ in range(MAX_TOOL_ROUNDS):
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
            final_text = _finalize_text(_final_text(response.content), research_contexts)
            # Stream deltas of the already-completed text so the UI sees typewriter output.
            if on_event:
                _stream_text(on_event, final_text)
                on_event("result", {"text": final_text})
            return final_text

        if response.stop_reason == "pause_turn":
            continue

        if response.stop_reason == "tool_use":
            tool_results = []
            unavailable_results = []
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
                    _stream_text(on_event, final_text)
                    on_event("result", {"text": final_text})
                return final_text
            continue

        final = _finalize_text(_final_text(response.content), research_contexts)
        if on_event:
            _stream_text(on_event, final)
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
