from __future__ import annotations

import os
import unittest
from unittest import mock

from server import clarify


class _FakeBlock:
    def __init__(self, type_: str, name: str | None = None, input_: dict | None = None):
        self.type = type_
        self.name = name
        self.input = input_


class _FakeResponse:
    def __init__(self, content):
        self.content = content


class _FakeMessages:
    def __init__(self, response):
        self._response = response
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self._response


class _FakeClient:
    def __init__(self, response):
        self.messages = _FakeMessages(response)


def _client_with(tool_input: dict) -> _FakeClient:
    block = _FakeBlock("tool_use", "plan_clarification", tool_input)
    return _FakeClient(_FakeResponse([_FakeBlock("text", None, None), block]))


class ClarifyTests(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["MARKETING_AGENT_CLARIFY_LLM"] = "1"

    def test_parses_and_caps(self) -> None:
        tool_input = {
            "needs_clarification": True,
            "questions": [
                {
                    "id": f"q{i}",
                    "question": f"问题{i}?",
                    "options": [{"label": f"选项{j}", "value": f"值{j}"} for j in range(6)],
                    # allow_custom omitted on purpose -> should default True
                }
                for i in range(5)
            ],
        }
        client = _client_with(tool_input)
        with mock.patch("server.clarify.llm.get_client", return_value=client):
            plan = clarify.plan_clarification("u1", "帮我写点东西", "zh")

        self.assertEqual(plan["source"], "llm")
        self.assertTrue(plan["needs_clarification"])
        self.assertLessEqual(len(plan["questions"]), 3)  # questions capped
        for q in plan["questions"]:
            self.assertLessEqual(len(q["options"]), 4)  # options capped
            self.assertTrue(q["allow_custom"])  # default
        # The request text is forwarded to the model.
        sent = client.messages.calls[0]["messages"][0]["content"]
        self.assertIn("帮我写点东西", sent)
        self.assertEqual(client.messages.calls[0]["tool_choice"], {"type": "tool", "name": "plan_clarification"})

    def test_needs_true_but_no_valid_questions_becomes_false(self) -> None:
        client = _client_with({"needs_clarification": True, "questions": []})
        with mock.patch("server.clarify.llm.get_client", return_value=client):
            plan = clarify.plan_clarification("u1", "写一篇小红书文案", "zh")
        self.assertFalse(plan["needs_clarification"])
        self.assertEqual(plan["questions"], [])

    def test_unavailable_without_client(self) -> None:
        with mock.patch("server.clarify.llm.get_client", return_value=None):
            plan = clarify.plan_clarification("u1", "写文案", "zh")
        self.assertEqual(plan["source"], "unavailable")
        self.assertFalse(plan["needs_clarification"])

    def test_disabled_via_env(self) -> None:
        os.environ["MARKETING_AGENT_CLARIFY_LLM"] = "0"
        plan = clarify.plan_clarification("u1", "写文案", "zh")
        self.assertEqual(plan["source"], "disabled")
        self.assertFalse(plan["needs_clarification"])

    def test_empty_prompt(self) -> None:
        plan = clarify.plan_clarification("u1", "   ", "zh")
        self.assertEqual(plan["source"], "empty")
        self.assertFalse(plan["needs_clarification"])

    def test_llm_error_degrades(self) -> None:
        client = _client_with({})
        client.messages.create = mock.Mock(side_effect=RuntimeError("boom"))
        with mock.patch("server.clarify.llm.get_client", return_value=client):
            plan = clarify.plan_clarification("u1", "写文案", "zh")
        self.assertEqual(plan["source"], "error")
        self.assertFalse(plan["needs_clarification"])


if __name__ == "__main__":
    unittest.main()
