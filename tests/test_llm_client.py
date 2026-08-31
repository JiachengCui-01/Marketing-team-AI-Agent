"""Tests for the Anthropic-shaped -> DeepSeek translation layer."""
from __future__ import annotations

import unittest
from unittest import mock

from marketing_agent import llm_client


class MessageTranslationTests(unittest.TestCase):
    def test_system_prompt_becomes_a_system_message(self) -> None:
        out = llm_client._to_openai_messages(
            [{"role": "user", "content": "hi"}], "you are helpful"
        )
        self.assertEqual(out[0], {"role": "system", "content": "you are helpful"})
        self.assertEqual(out[1], {"role": "user", "content": "hi"})

    def test_image_block_becomes_a_data_url_part(self) -> None:
        out = llm_client._to_openai_messages(
            [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "look"},
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": "QUJD",
                            },
                        },
                    ],
                }
            ],
            None,
        )
        parts = out[0]["content"]
        self.assertEqual(parts[0], {"type": "text", "text": "look"})
        self.assertEqual(
            parts[1],
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,QUJD"}},
        )

    def test_assistant_tool_use_becomes_tool_calls(self) -> None:
        blocks = [
            llm_client.TextBlock(text="dispatching"),
            llm_client.ThinkingBlock(thinking="internal"),
            llm_client.ToolUseBlock(id="call_1", name="delegate", input={"task": "write"}),
        ]
        out = llm_client._to_openai_messages([{"role": "assistant", "content": blocks}], None)
        self.assertEqual(out[0]["content"], "dispatching")
        # Thinking is dropped: DeepSeek does not accept reasoning_content back.
        self.assertNotIn("internal", out[0]["content"])
        call = out[0]["tool_calls"][0]
        self.assertEqual(call["id"], "call_1")
        self.assertEqual(call["function"]["name"], "delegate")
        self.assertEqual(call["function"]["arguments"], '{"task": "write"}')

    def test_tool_results_fan_out_to_tool_messages(self) -> None:
        out = llm_client._to_openai_messages(
            [
                {
                    "role": "user",
                    "content": [
                        {"type": "tool_result", "tool_use_id": "call_1", "content": "done"},
                        {
                            "type": "tool_result",
                            "tool_use_id": "call_2",
                            "content": "boom",
                            "is_error": True,
                        },
                    ],
                }
            ],
            None,
        )
        self.assertEqual(out[0], {"role": "tool", "tool_call_id": "call_1", "content": "done"})
        self.assertEqual(out[1]["role"], "tool")
        self.assertEqual(out[1]["tool_call_id"], "call_2")
        self.assertIn("boom", out[1]["content"])


class ToolTranslationTests(unittest.TestCase):
    def test_anthropic_schema_becomes_an_openai_function(self) -> None:
        schema = {"type": "object", "properties": {"q": {"type": "string"}}}
        out = llm_client._to_openai_tools(
            [{"name": "search", "description": "find", "input_schema": schema}]
        )
        self.assertEqual(
            out,
            [{"type": "function", "function": {"name": "search", "description": "find", "parameters": schema}}],
        )

    def test_server_side_tool_types_are_dropped(self) -> None:
        out = llm_client._to_openai_tools(
            [
                {"type": "web_search_20250305", "name": "web_search", "max_uses": 3},
                {"type": "code_execution_20260120", "name": "code_execution"},
            ]
        )
        self.assertEqual(out, [])

    def test_forced_tool_choice_disables_thinking(self) -> None:
        # DeepSeek rejects a forced tool_choice while thinking mode is on.
        choice, forced = llm_client._to_openai_tool_choice({"type": "tool", "name": "plan"})
        self.assertEqual(choice, {"type": "function", "function": {"name": "plan"}})
        self.assertTrue(forced)
        self.assertEqual(
            llm_client._thinking_param({"type": "adaptive"}, {"effort": "high"}, True),
            {"type": "disabled"},
        )

    def test_effort_maps_onto_deepseek_thinking(self) -> None:
        self.assertEqual(
            llm_client._thinking_param(None, {"effort": "medium"}, False),
            {"type": "enabled", "effort": "medium"},
        )
        # DeepSeek has no tier above "high"; the two Anthropic tiers above clamp down.
        self.assertEqual(
            llm_client._thinking_param(None, {"effort": "max"}, False),
            {"type": "enabled", "effort": "high"},
        )


class ResponseParsingTests(unittest.TestCase):
    def test_text_response(self) -> None:
        msg = llm_client._parse_response(
            {
                "choices": [{"message": {"content": "hello"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 4},
            },
            "deepseek-v4-pro",
        )
        self.assertEqual(msg.stop_reason, "end_turn")
        self.assertEqual(msg.content[0].type, "text")
        self.assertEqual(msg.content[0].text, "hello")
        self.assertEqual(msg.usage.input_tokens, 10)
        self.assertEqual(msg.usage.output_tokens, 4)

    def test_tool_calls_normalize_to_tool_use(self) -> None:
        msg = llm_client._parse_response(
            {
                "choices": [
                    {
                        "message": {
                            "content": "",
                            "reasoning_content": "thinking...",
                            "tool_calls": [
                                {
                                    "id": "call_9",
                                    "function": {"name": "delegate", "arguments": '{"task":"x"}'},
                                }
                            ],
                        },
                        # DeepSeek sometimes reports "stop" alongside tool_calls.
                        "finish_reason": "stop",
                    }
                ]
            },
            "deepseek-v4-pro",
        )
        self.assertEqual(msg.stop_reason, "tool_use")
        kinds = [b.type for b in msg.content]
        self.assertEqual(kinds, ["thinking", "tool_use"])
        self.assertEqual(msg.content[1].input, {"task": "x"})

    def test_malformed_tool_arguments_degrade_to_empty_input(self) -> None:
        msg = llm_client._parse_response(
            {
                "choices": [
                    {
                        "message": {
                            "tool_calls": [
                                {"id": "c1", "function": {"name": "t", "arguments": "{not json"}}
                            ]
                        },
                        "finish_reason": "tool_calls",
                    }
                ]
            },
            "deepseek-v4-pro",
        )
        self.assertEqual(msg.content[0].input, {})

    def test_length_finish_reason_maps_to_max_tokens(self) -> None:
        msg = llm_client._parse_response(
            {"choices": [{"message": {"content": "cut"}, "finish_reason": "length"}]},
            "deepseek-v4-pro",
        )
        self.assertEqual(msg.stop_reason, "max_tokens")


class ModelRoutingTests(unittest.TestCase):
    def test_image_requests_route_to_the_vision_model(self) -> None:
        client = llm_client.DeepSeek(api_key="test-key")
        captured: dict = {}

        def fake_post(path, body, extra_headers=None):
            captured["body"] = body
            return {"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]}

        with mock.patch.object(client, "_post", side_effect=fake_post):
            client.messages.create(
                model="deepseek-v4-pro",
                max_tokens=32,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {"type": "base64", "media_type": "image/png", "data": "QUJD"},
                            }
                        ],
                    }
                ],
            )
        # The text models reject image content, so the shim swaps the model.
        self.assertEqual(captured["body"]["model"], llm_client.VISION_MODEL)

    def test_text_requests_keep_the_requested_model(self) -> None:
        client = llm_client.DeepSeek(api_key="test-key")
        captured: dict = {}

        with mock.patch.object(
            client,
            "_post",
            side_effect=lambda path, body, extra_headers=None: (
                captured.update(body)
                or {"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]}
            ),
        ):
            client.messages.create(
                model="deepseek-v4-pro",
                max_tokens=32,
                messages=[{"role": "user", "content": "hi"}],
            )
        self.assertEqual(captured["model"], "deepseek-v4-pro")


class ErrorMappingTests(unittest.TestCase):
    def _response(self, status: int, payload: dict):
        response = mock.Mock()
        response.status_code = status
        response.json.return_value = payload
        response.text = str(payload)
        return response

    def test_401_becomes_authentication_error(self) -> None:
        exc = llm_client._status_error(self._response(401, {"error": {"message": "bad key"}}))
        self.assertIsInstance(exc, llm_client.AuthenticationError)
        self.assertIsInstance(exc, llm_client.APIError)

    def test_402_is_reported_as_insufficient_balance(self) -> None:
        exc = llm_client._status_error(self._response(402, {"error": {"message": "no funds"}}))
        self.assertIn("insufficient balance", str(exc))

    def test_429_becomes_rate_limit_error(self) -> None:
        exc = llm_client._status_error(self._response(429, {"error": {"message": "slow down"}}))
        self.assertIsInstance(exc, llm_client.RateLimitError)

    def test_missing_api_key_raises(self) -> None:
        with mock.patch.dict("os.environ", {"DEEPSEEK_API_KEY": ""}, clear=False):
            with self.assertRaises(llm_client.APIError):
                llm_client.DeepSeek()


if __name__ == "__main__":
    unittest.main()
