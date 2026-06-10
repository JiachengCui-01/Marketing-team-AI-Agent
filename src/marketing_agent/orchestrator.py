"""Orchestrator — routes user requests to sub-agents and synthesizes results."""
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
from .tools.delegation_tools import DELEGATION_TOOLS

SYSTEM = """You are the chief of staff for an enterprise marketing team. Your job is to
understand the user's request, decompose it into specialist tasks, dispatch those tasks
to the right specialists, and synthesize their output into a single clean deliverable.

You have three specialists, accessible only via the delegate_* tools:

- delegate_to_content_agent — for any copywriting (social, blog, email, ads)
- delegate_to_analytics_agent — for any CSV/data/KPI/performance analysis
- delegate_to_research_agent — for any external/market/competitor/trend research

Hard rules:

1. NEVER write marketing copy yourself. Always delegate to the content agent.
2. NEVER compute metrics or interpret CSVs yourself. Always delegate to analytics.
3. NEVER claim external facts (competitor news, market data) without delegating to research.
4. When multiple specialists are needed, prefer dispatching them in parallel (multiple
   tool_use blocks in a single response) when the tasks are independent. Only chain them
   sequentially when later tasks need earlier results as input.
5. After all specialists return, write a final synthesized response in well-formatted
   markdown. Lead with a 2-3 sentence executive summary, then include each specialist's
   output under clear headings.
6. If the user's request is small and clearly fits one specialist (e.g. "write a tweet"),
   just delegate to that one specialist and pass through the result with minimal framing.
7. If a specialist returns an unavailable/error result, do not retry the same specialist.
   Synthesize the limitation immediately and tell the user what needs to be fixed.

Be decisive. Don't ask clarifying questions unless the request is genuinely ambiguous.
"""

# Map tool name -> (callable, kwargs filter). Each callable returns a string.
def _dispatch(client: anthropic.Anthropic, name: str, payload: dict) -> str:
    # Use a fresh SDK client for specialist calls. Reusing the orchestrator's
    # HTTP connection can surface intermittent TLS/keep-alive disconnects during
    # server-side tools such as web_search.
    specialist_client = anthropic.Anthropic()
    if name == "delegate_to_content_agent":
        return content_agent.run(specialist_client, **payload)
    if name == "delegate_to_analytics_agent":
        return analytics_agent.run(specialist_client, **payload)
    if name == "delegate_to_research_agent":
        return research_agent.run(specialist_client, **payload)
    return f"Error: unknown specialist '{name}'."


def run_orchestrator(
    client: anthropic.Anthropic,
    conversation: Conversation,
    user_message: str,
    on_event: Callable[[str, dict], None] | None = None,
) -> str:
    """Process one user turn end-to-end. Mutates ``conversation`` with new messages."""
    conversation.add_user(user_message)
    failed_specialists: set[str] = set()

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
            final_text = _final_text(response.content)
            if on_event:
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
                        "unavailable/error result for this request. I will not retry it "
                        "again in the same turn."
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
                    result = _dispatch(client, block.name, block.input)
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
                    on_event("result", {"text": final_text})
                return final_text
            continue

        # max_tokens / refusal / other
        return _final_text(response.content)

    return "[Orchestrator stopped: exceeded MAX_TOOL_ROUNDS.]"


def _final_text(content: list) -> str:
    return "\n".join(b.text for b in content if b.type == "text").strip()


def _is_unavailable_result(text: str) -> bool:
    lowered = text.lower()
    return (
        "## research unavailable" in lowered
        or "## specialist unavailable" in lowered
        or "error:" in lowered
        or "unavailable" in lowered
    )
