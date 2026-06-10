"""Shared tool-use loop used by every sub-agent and (mostly) by the orchestrator."""
from __future__ import annotations

from typing import Any, Callable

import anthropic

from ..config import (
    MAX_TOOL_ROUNDS,
    MODEL_ID,
    SUBAGENT_EFFORT,
    SUBAGENT_MAX_TOKENS,
)


def _extract_text(content: list[Any]) -> str:
    """Concatenate all text blocks from an assistant response."""
    return "\n".join(block.text for block in content if block.type == "text").strip()


def run_agent(
    client: anthropic.Anthropic,
    system: str,
    user_message: str,
    tools: list[dict] | None = None,
    *,
    effort: str = SUBAGENT_EFFORT,
    max_tokens: int = SUBAGENT_MAX_TOKENS,
    client_tool_handlers: dict[str, Callable[[dict], str]] | None = None,
    on_event: Callable[[str, Any], None] | None = None,
) -> str:
    """Run a single agent turn to completion.

    - Server-side tools (web_search, code_execution) resolve automatically.
    - Client-side tools are dispatched via ``client_tool_handlers`` keyed by tool name;
      each handler takes the parsed ``input`` dict and returns a string result.
    - ``on_event`` is called for observability with (event_type, payload).

    Returns the final assistant text.
    """
    messages: list[dict] = [{"role": "user", "content": user_message}]
    tools = tools or []
    handlers = client_tool_handlers or {}

    for _ in range(MAX_TOOL_ROUNDS):
        response = client.messages.create(
            model=MODEL_ID,
            max_tokens=max_tokens,
            system=system,
            thinking={"type": "adaptive"},
            output_config={"effort": effort},
            tools=tools,
            messages=messages,
        )

        if on_event:
            on_event("response", response)

        # Append the assistant turn verbatim — preserve thinking/tool_use blocks.
        messages.append({"role": "assistant", "content": response.content})

        stop = response.stop_reason

        if stop == "end_turn":
            return _extract_text(response.content)

        if stop == "pause_turn":
            # Server-side tool hit iteration cap mid-flight; loop to resume.
            continue

        if stop == "tool_use":
            # Resolve any client-side tool calls. Server tools are already resolved.
            tool_results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                handler = handlers.get(block.name)
                if handler is None:
                    # Unknown tool — tell the model.
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": f"Error: no handler for tool '{block.name}'.",
                        "is_error": True,
                    })
                    continue
                try:
                    result = handler(block.input)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result,
                    })
                except Exception as exc:  # noqa: BLE001
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": f"Tool execution failed: {exc}",
                        "is_error": True,
                    })

            if not tool_results:
                # tool_use stop but no client tools to run — likely all server-side, loop again.
                continue

            messages.append({"role": "user", "content": tool_results})
            continue

        # Anything else (max_tokens, refusal, etc.) — return what we have.
        text = _extract_text(response.content)
        if stop == "refusal":
            return text or "[The model refused to respond.]"
        if stop == "max_tokens":
            return (text or "") + "\n\n[Response truncated: max_tokens reached.]"
        return text

    return "[Agent stopped: exceeded MAX_TOOL_ROUNDS.]"
