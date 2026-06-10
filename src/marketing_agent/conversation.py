"""Lightweight conversation state for the orchestrator across CLI turns."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Conversation:
    """Holds the orchestrator's running message history for a REPL session."""

    messages: list[dict[str, Any]] = field(default_factory=list)

    def add_user(self, text: str) -> None:
        self.messages.append({"role": "user", "content": text})

    def add_assistant(self, content: list[Any]) -> None:
        """Append the assistant turn verbatim — preserves thinking and tool_use blocks."""
        self.messages.append({"role": "assistant", "content": content})

    def add_tool_results(self, results: list[dict[str, Any]]) -> None:
        self.messages.append({"role": "user", "content": results})

    def reset(self) -> None:
        self.messages.clear()
