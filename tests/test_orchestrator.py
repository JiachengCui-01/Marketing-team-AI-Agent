from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest import mock

from marketing_agent import orchestrator
from marketing_agent.conversation import Conversation


class OrchestratorSourceTests(unittest.TestCase):
    def test_research_sources_survive_final_synthesis(self) -> None:
        tool_response = SimpleNamespace(
            stop_reason="tool_use",
            content=[
                SimpleNamespace(
                    type="tool_use",
                    id="tool-1",
                    name="delegate_to_research_agent",
                    input={"task": "Research AI", "topics": ["AI"], "response_language": "en"},
                )
            ],
            usage=SimpleNamespace(input_tokens=1, output_tokens=1),
        )
        final_response = SimpleNamespace(
            stop_reason="end_turn",
            content=[
                SimpleNamespace(
                    type="text",
                    text="## Summary\nAI competitors are moving quickly.\n\n## Findings\n- Market activity is accelerating.",
                )
            ],
            usage=SimpleNamespace(input_tokens=1, output_tokens=1),
        )
        client = SimpleNamespace(messages=SimpleNamespace(create=mock.Mock(side_effect=[tool_response, final_response])))
        events: list[tuple[str, dict]] = []

        with mock.patch.object(
            orchestrator.research_agent,
            "run",
            return_value=(
                "## Summary\nResearch result. [Reuters](https://www.reuters.com/technology/ai/)\n\n"
                "## Source Credibility\nThis summary prioritizes Tier 1/Tier 2 sources.\n"
                "1. Tier 2 - authoritative media / official website (80): "
                "[reuters.com](https://www.reuters.com/technology/ai/)"
            ),
        ):
            result = orchestrator.run_orchestrator(
                client,  # type: ignore[arg-type]
                Conversation(),
                "Research AI competitors",
                on_event=lambda event, payload: events.append((event, payload)),
            )

        self.assertIn("[reuters.com](https://www.reuters.com/technology/ai/)", result)
        self.assertIn("## Source Credibility", result)
        self.assertIn("Tier 2", result)
        self.assertTrue(any(event == "result" and "reuters.com" in payload["text"] for event, payload in events))


if __name__ == "__main__":
    unittest.main()
