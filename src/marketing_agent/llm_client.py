"""DeepSeek client exposing an Anthropic-Messages-shaped surface.

The whole agent stack — orchestrator, OA copilot, sub-agents, and the
memory/clarify/query-rewrite helpers — was written against Anthropic's Messages
API: it walks ``response.content`` blocks, branches on ``stop_reason``, and
feeds ``tool_result`` blocks back in on the next turn. DeepSeek speaks the
OpenAI chat-completions dialect instead.

Rather than rewrite every call site (and the persisted conversation shape with
it), this module translates at the boundary: Anthropic-shaped kwargs in, OpenAI
JSON on the wire, Anthropic-shaped blocks back out. Only the surface the app
actually uses is implemented.

DeepSeek quirks handled here:

- Thinking mode is on by default and rejects a forced ``tool_choice``, so any
  forced choice implies ``thinking={"type": "disabled"}``.
- The text models reject image content, so a request carrying an image is
  routed to the vision model automatically.
- Anthropic's server-side tools (``web_search``, ``code_execution``) have no
  DeepSeek equivalent and are dropped here; the agents that needed them supply
  client-side replacements instead (``tools/web_search.py``, ``tools/code_exec.py``).
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any

import httpx

from .config import (
    DEEPSEEK_BASE_URL,
    DEEPSEEK_TIMEOUT_SECONDS,
    MODEL_ID,
    VISION_MODEL,
    VISION_CAPABLE_MODELS,
)

__all__ = [
    "DeepSeek",
    "APIError",
    "APIStatusError",
    "APIConnectionError",
    "AuthenticationError",
    "RateLimitError",
    "TextBlock",
    "ThinkingBlock",
    "ToolUseBlock",
]


# --------------------------------------------------------------------------
# Errors — mirror the anthropic.* names the call sites already catch.
# --------------------------------------------------------------------------

class APIError(Exception):
    """Any failure talking to the model API."""

    def __init__(self, message: str, *, status_code: int | None = None, body: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.body = body


class APIStatusError(APIError):
    """The API returned a non-2xx response."""


class APIConnectionError(APIError):
    """The API could not be reached (DNS, TLS, timeout, refused)."""


class AuthenticationError(APIStatusError):
    """401/403 — bad or missing API key."""


class RateLimitError(APIStatusError):
    """429 — too many requests."""


# --------------------------------------------------------------------------
# Response blocks — duck-compatible with anthropic's content blocks.
# --------------------------------------------------------------------------

@dataclass
class TextBlock:
    text: str
    type: str = "text"
    # Anthropic's web_search attaches citations here; DeepSeek never does, but
    # research_agent reads the attribute so it must exist.
    citations: list = field(default_factory=list)


@dataclass
class ThinkingBlock:
    thinking: str
    type: str = "thinking"


@dataclass
class ToolUseBlock:
    id: str
    name: str
    input: dict
    type: str = "tool_use"


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class Message:
    content: list[Any]
    stop_reason: str | None
    usage: Usage
    model: str
    role: str = "assistant"
    type: str = "message"


# --------------------------------------------------------------------------
# Request translation
# --------------------------------------------------------------------------

# Anthropic effort levels -> DeepSeek thinking effort. DeepSeek has no tier
# above "high", so the two Anthropic tiers above it clamp down to it.
_EFFORT_MAP = {
    "low": "low",
    "medium": "medium",
    "high": "high",
    "xhigh": "high",
    "max": "high",
}

_FINISH_REASONS = {
    "stop": "end_turn",
    "tool_calls": "tool_use",
    "length": "max_tokens",
    "content_filter": "refusal",
    "insufficient_system_resource": "max_tokens",
}


def _battr(block: Any, name: str, default: Any = None) -> Any:
    """Read a field off a content block that may be a dict or an object."""
    if isinstance(block, dict):
        return block.get(name, default)
    return getattr(block, name, default)


def _image_part(source: dict) -> dict | None:
    """Convert an Anthropic image block source into an OpenAI ``image_url`` part."""
    if not isinstance(source, dict):
        return None
    if source.get("type") == "base64":
        media_type = source.get("media_type") or "image/png"
        data = source.get("data") or ""
        if not data:
            return None
        return {"type": "image_url", "image_url": {"url": f"data:{media_type};base64,{data}"}}
    if source.get("type") == "url" and source.get("url"):
        return {"type": "image_url", "image_url": {"url": source["url"]}}
    return None


def _tool_result_text(block: Any) -> str:
    """Flatten a tool_result block's content down to a string."""
    content = _battr(block, "content", "")
    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        text = "\n".join(
            str(_battr(part, "text", "")) for part in content if _battr(part, "type") == "text"
        )
    else:
        text = str(content or "")
    if _battr(block, "is_error"):
        text = f"[error] {text}" if text else "[error]"
    return text


def _user_messages(content: Any) -> list[dict]:
    """Translate one Anthropic user turn into one or more OpenAI messages.

    A single Anthropic turn can carry several ``tool_result`` blocks; OpenAI
    wants one ``role: "tool"`` message per result, so this fans out.
    """
    if isinstance(content, str):
        return [{"role": "user", "content": content}]
    if not isinstance(content, list):
        return [{"role": "user", "content": str(content or "")}]

    out: list[dict] = []
    parts: list[dict] = []

    def flush() -> None:
        if not parts:
            return
        if len(parts) == 1 and parts[0]["type"] == "text":
            out.append({"role": "user", "content": parts[0]["text"]})
        else:
            out.append({"role": "user", "content": list(parts)})
        parts.clear()

    for block in content:
        kind = _battr(block, "type")
        if kind == "tool_result":
            flush()
            out.append({
                "role": "tool",
                "tool_call_id": _battr(block, "tool_use_id") or "",
                "content": _tool_result_text(block) or "(empty)",
            })
        elif kind == "image":
            part = _image_part(_battr(block, "source") or {})
            if part:
                parts.append(part)
        elif kind == "text":
            text = str(_battr(block, "text", "") or "")
            if text:
                parts.append({"type": "text", "text": text})

    flush()
    return out or [{"role": "user", "content": ""}]


def _assistant_message(content: Any) -> list[dict]:
    """Translate an assistant turn (text + tool_use blocks) back to OpenAI shape.

    Thinking blocks are dropped: DeepSeek returns ``reasoning_content`` but does
    not accept it back on a later turn.
    """
    if isinstance(content, str):
        return [{"role": "assistant", "content": content}]
    if not isinstance(content, list):
        return [{"role": "assistant", "content": str(content or "")}]

    texts: list[str] = []
    tool_calls: list[dict] = []
    for block in content:
        kind = _battr(block, "type")
        if kind == "text":
            text = str(_battr(block, "text", "") or "")
            if text:
                texts.append(text)
        elif kind == "tool_use":
            tool_calls.append({
                "id": _battr(block, "id") or f"call_{len(tool_calls)}",
                "type": "function",
                "function": {
                    "name": _battr(block, "name") or "",
                    "arguments": json.dumps(_battr(block, "input") or {}, ensure_ascii=False),
                },
            })

    msg: dict = {"role": "assistant", "content": "\n".join(texts)}
    if tool_calls:
        msg["tool_calls"] = tool_calls
    return [msg]


def _to_openai_messages(messages: list[dict], system: str | None) -> list[dict]:
    out: list[dict] = []
    if system:
        out.append({"role": "system", "content": system})
    for msg in messages or []:
        role = msg.get("role", "user")
        content = msg.get("content")
        if role == "assistant":
            out.extend(_assistant_message(content))
        elif role == "system":
            out.append({"role": "system", "content": content if isinstance(content, str) else str(content)})
        else:
            out.extend(_user_messages(content))
    return out


def _to_openai_tools(tools: list[dict] | None) -> list[dict]:
    """Convert Anthropic tool schemas; silently drop server-side tool types."""
    out: list[dict] = []
    for tool in tools or []:
        if not isinstance(tool, dict):
            continue
        if "input_schema" in tool:
            out.append({
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool.get("description", ""),
                    "parameters": tool["input_schema"],
                },
            })
        elif tool.get("type") == "function" and "function" in tool:
            out.append(tool)
        # Anything else is an Anthropic server-side tool (web_search_*,
        # code_execution_*) with no DeepSeek counterpart — skip it.
    return out


def _to_openai_tool_choice(tool_choice: Any) -> tuple[Any, bool]:
    """Return ``(openai_tool_choice, forces_a_tool)``.

    The second value matters because DeepSeek rejects a forced choice while
    thinking mode is on.
    """
    if tool_choice is None:
        return None, False
    if isinstance(tool_choice, str):
        return tool_choice, tool_choice == "required"
    if not isinstance(tool_choice, dict):
        return None, False
    kind = tool_choice.get("type")
    if kind == "tool" and tool_choice.get("name"):
        return {"type": "function", "function": {"name": tool_choice["name"]}}, True
    if kind == "function":
        return tool_choice, True
    if kind == "any":
        return "required", True
    if kind == "auto":
        return "auto", False
    if kind == "none":
        return "none", False
    return None, False


def _thinking_param(thinking: Any, output_config: Any, forced_tool: bool) -> dict:
    """Map Anthropic's thinking/effort knobs onto DeepSeek's ``thinking`` field."""
    if forced_tool:
        # DeepSeek: "Thinking mode does not support this tool_choice".
        return {"type": "disabled"}
    if isinstance(thinking, dict) and thinking.get("type") == "disabled":
        return {"type": "disabled"}
    effort = None
    if isinstance(output_config, dict):
        effort = output_config.get("effort")
    if isinstance(thinking, dict) and thinking.get("effort"):
        effort = thinking["effort"]
    mapped = _EFFORT_MAP.get(str(effort).lower()) if effort else None
    return {"type": "enabled", "effort": mapped} if mapped else {"type": "enabled"}


def _has_image(messages: list[dict]) -> bool:
    for msg in messages:
        content = msg.get("content")
        if isinstance(content, list) and any(
            isinstance(part, dict) and part.get("type") == "image_url" for part in content
        ):
            return True
    return False


def _resolve_model(model: str | None, *, has_image: bool) -> str:
    model = model or MODEL_ID
    if has_image and model not in VISION_CAPABLE_MODELS:
        return VISION_MODEL
    return model


# --------------------------------------------------------------------------
# Client
# --------------------------------------------------------------------------

class _Messages:
    def __init__(self, client: "DeepSeek") -> None:
        self._client = client

    def create(
        self,
        *,
        model: str | None = None,
        messages: list[dict],
        max_tokens: int = 4096,
        system: str | None = None,
        tools: list[dict] | None = None,
        tool_choice: Any = None,
        thinking: Any = None,
        output_config: Any = None,
        temperature: float | None = None,
        extra_headers: dict[str, str] | None = None,
        **_ignored: Any,
    ) -> Message:
        wire_messages = _to_openai_messages(messages, system)
        has_image = _has_image(wire_messages)
        choice, forced_tool = _to_openai_tool_choice(tool_choice)
        wire_tools = _to_openai_tools(tools)

        body: dict[str, Any] = {
            "model": _resolve_model(model, has_image=has_image),
            "messages": wire_messages,
            "max_tokens": max_tokens,
            "thinking": _thinking_param(thinking, output_config, forced_tool and bool(wire_tools)),
        }
        if wire_tools:
            body["tools"] = wire_tools
            if choice is not None:
                body["tool_choice"] = choice
        if temperature is not None:
            body["temperature"] = temperature

        data = self._client._post("/chat/completions", body, extra_headers=extra_headers)
        return _parse_response(data, body["model"])


def _parse_response(data: dict, model: str) -> Message:
    choices = data.get("choices") or []
    if not choices:
        raise APIError("The model API returned no choices.")
    choice = choices[0]
    raw = choice.get("message") or {}

    blocks: list[Any] = []
    reasoning = raw.get("reasoning_content")
    if reasoning:
        blocks.append(ThinkingBlock(thinking=str(reasoning)))
    text = raw.get("content")
    if text:
        blocks.append(TextBlock(text=str(text)))

    tool_blocks: list[ToolUseBlock] = []
    for index, call in enumerate(raw.get("tool_calls") or []):
        fn = call.get("function") or {}
        try:
            parsed = json.loads(fn.get("arguments") or "{}")
        except (TypeError, ValueError):
            parsed = {}
        if not isinstance(parsed, dict):
            parsed = {"value": parsed}
        tool_blocks.append(
            ToolUseBlock(
                id=call.get("id") or f"call_{index}",
                name=fn.get("name") or "",
                input=parsed,
            )
        )
    blocks.extend(tool_blocks)

    stop = _FINISH_REASONS.get(choice.get("finish_reason") or "stop", "end_turn")
    if tool_blocks:
        # DeepSeek sometimes reports finish_reason="stop" alongside tool_calls;
        # the agent loops key off stop_reason, so normalize it.
        stop = "tool_use"

    usage_raw = data.get("usage") or {}
    usage = Usage(
        input_tokens=int(usage_raw.get("prompt_tokens") or 0),
        output_tokens=int(usage_raw.get("completion_tokens") or 0),
    )
    return Message(content=blocks, stop_reason=stop, usage=usage, model=data.get("model") or model)


class DeepSeek:
    """Minimal DeepSeek client with an ``anthropic.Anthropic``-shaped surface."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: float | None = None,
    ) -> None:
        self.api_key = api_key or os.environ.get("DEEPSEEK_API_KEY", "")
        if not self.api_key:
            raise APIError("DEEPSEEK_API_KEY is not set.")
        self.base_url = (base_url or os.environ.get("DEEPSEEK_BASE_URL") or DEEPSEEK_BASE_URL).rstrip("/")
        self.timeout = timeout or DEEPSEEK_TIMEOUT_SECONDS
        self._http = httpx.Client(
            timeout=httpx.Timeout(self.timeout, connect=15.0),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )
        self.messages = _Messages(self)

    def _post(self, path: str, body: dict, *, extra_headers: dict[str, str] | None = None) -> dict:
        url = f"{self.base_url}{path}"
        try:
            response = self._http.post(url, json=body, headers=extra_headers or None)
        except httpx.HTTPError as exc:
            raise APIConnectionError(f"Could not reach {url}: {exc}") from exc

        if response.status_code >= 400:
            raise _status_error(response)
        try:
            return response.json()
        except ValueError as exc:
            raise APIError(f"The model API returned a non-JSON response: {response.text[:400]}") from exc

    def close(self) -> None:
        self._http.close()


def _status_error(response: httpx.Response) -> APIStatusError:
    try:
        payload = response.json()
        message = str((payload.get("error") or {}).get("message") or payload)
    except ValueError:
        payload = response.text
        message = response.text[:400]
    detail = f"{response.status_code} {message}"
    if response.status_code in (401, 403):
        return AuthenticationError(detail, status_code=response.status_code, body=payload)
    if response.status_code == 429:
        return RateLimitError(detail, status_code=response.status_code, body=payload)
    if response.status_code == 402:
        return APIStatusError(
            f"{detail} (insufficient balance)", status_code=response.status_code, body=payload
        )
    return APIStatusError(detail, status_code=response.status_code, body=payload)
