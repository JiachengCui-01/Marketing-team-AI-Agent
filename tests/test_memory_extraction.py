from __future__ import annotations

import os
import types
import unittest
from unittest import mock

from server import memory_extraction
from server.memory_extraction import Observation


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


class MemoryExtractionTests(unittest.TestCase):
    def test_llm_tool_output_is_parsed(self) -> None:
        response = _FakeResponse([
            _FakeBlock("text", None, None),
            _FakeBlock(
                "tool_use",
                "record_marketing_profile",
                {
                    "products": [{"value": "牙科诊所预约系统", "explicit": True}],
                    "channels": [{"value": "LinkedIn", "explicit": False}],
                    "unknown_field": [{"value": "ignore me", "explicit": True}],
                },
            ),
        ])
        client = _FakeClient(response)
        with mock.patch("server.memory_extraction.llm.get_client", return_value=client):
            observations = memory_extraction.extract_observations(
                ["我们的产品是牙科诊所预约系统"], use_llm=True
            )

        self.assertIn(Observation("products", "牙科诊所预约系统", True), observations)
        self.assertIn(Observation("channels", "LinkedIn", False), observations)
        # Unknown fields are dropped.
        self.assertTrue(all(obs.field != "unknown_field" for obs in observations))
        # The cheap extraction model was used with a forced tool choice.
        call = client.messages.calls[0]
        self.assertEqual(call["tool_choice"], {"type": "tool", "name": "record_marketing_profile"})

    def test_falls_back_to_heuristic_without_client(self) -> None:
        with mock.patch("server.memory_extraction.llm.get_client", return_value=None):
            observations = memory_extraction.extract_observations(
                ["写一篇小红书文案"], use_llm=True
            )
        # Heuristic keyword path recognizes the channel (incidental → not explicit).
        self.assertIn(Observation("channels", "Little Red Book", False), observations)

    def test_llm_failure_degrades_to_heuristic(self) -> None:
        client = _FakeClient(None)
        client.messages.create = mock.Mock(side_effect=RuntimeError("boom"))
        with mock.patch("server.memory_extraction.llm.get_client", return_value=client):
            observations = memory_extraction.extract_observations(
                ["写一篇小红书文案"], use_llm=True
            )
        self.assertIn(Observation("channels", "Little Red Book", False), observations)


if __name__ == "__main__":
    unittest.main()
