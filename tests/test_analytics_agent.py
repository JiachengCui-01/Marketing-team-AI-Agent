from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from marketing_agent.agents import analytics_agent


class AnalyticsAgentTests(unittest.TestCase):
    def _write_temp(self, name: str, content: bytes) -> Path:
        tmp = Path(tempfile.mkdtemp()) / name
        tmp.write_bytes(content)
        return tmp

    def test_passes_run_python_tool_without_inlining_the_data(self) -> None:
        big_csv = "channel,clicks\n" + "\n".join(f"linkedin,{i}" for i in range(5000))
        path = self._write_temp("campaign.csv", big_csv.encode("utf-8"))

        captured: dict = {}

        def fake_run_agent(**kwargs):
            captured.update(kwargs)
            return "## Key Metrics\nok"

        client = mock.Mock()

        with mock.patch.object(analytics_agent, "run_agent", side_effect=fake_run_agent):
            result = analytics_agent.run(
                client=client,
                task="Analyze channel performance",
                data_path=str(path),
                questions=["Which channel has the most clicks?"],
            )

        self.assertEqual(result, "## Key Metrics\nok")

        brief = captured["user_message"]
        self.assertIsInstance(brief, str)
        # The raw data must NOT be inlined into the prompt — only the filename.
        self.assertNotIn("linkedin,4999", brief)
        self.assertIn("Analyze channel performance", brief)
        self.assertIn("campaign.csv", brief)
        self.assertIn("Which channel has the most clicks?", brief)

        # The local execution tool is wired up with a handler bound to this file.
        self.assertEqual(captured["tools"][0]["name"], "run_python")
        self.assertIn("run_python", captured["client_tool_handlers"])

    def test_handler_executes_against_the_data_file(self) -> None:
        path = self._write_temp("campaign.csv", b"channel,clicks\nlinkedin,7\n")
        captured: dict = {}

        with mock.patch.object(
            analytics_agent, "run_agent", side_effect=lambda **kw: captured.update(kw) or "ok"
        ):
            analytics_agent.run(client=mock.Mock(), task="t", data_path=str(path))

        handler = captured["client_tool_handlers"]["run_python"]
        output = handler({"code": "print(open('campaign.csv').read().strip())"})
        self.assertIn("linkedin,7", output)

    def test_csv_path_alias_still_accepted(self) -> None:
        path = self._write_temp("data.json", json.dumps([{"a": 1}]).encode("utf-8"))

        with mock.patch.object(analytics_agent, "run_agent", return_value="ok"):
            result = analytics_agent.run(client=mock.Mock(), task="t", csv_path=str(path))

        self.assertEqual(result, "ok")

    def test_missing_file_returns_error(self) -> None:
        with mock.patch.object(analytics_agent, "run_agent") as run_agent:
            result = analytics_agent.run(
                client=mock.Mock(), task="t", data_path="/no/such/file.csv"
            )
        self.assertIn("not found", result)
        run_agent.assert_not_called()

    def test_disabled_code_execution_degrades(self) -> None:
        path = self._write_temp("campaign.csv", b"channel,clicks\nlinkedin,7\n")
        with mock.patch.object(analytics_agent, "code_exec_enabled", return_value=False):
            result = analytics_agent.run(client=mock.Mock(), task="t", data_path=str(path))
        self.assertIn("Analysis Unavailable", result)


if __name__ == "__main__":
    unittest.main()
