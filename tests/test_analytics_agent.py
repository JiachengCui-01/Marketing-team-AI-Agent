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

    def test_uploads_file_and_passes_container_upload_without_inlining(self) -> None:
        big_csv = "channel,clicks\n" + "\n".join(f"linkedin,{i}" for i in range(5000))
        path = self._write_temp("campaign.csv", big_csv.encode("utf-8"))

        captured: dict = {}

        def fake_run_agent(**kwargs):
            captured["user_message"] = kwargs["user_message"]
            captured["tools"] = kwargs["tools"]
            captured["extra_headers"] = kwargs.get("extra_headers")
            return "## Key Metrics\nok"

        client = mock.Mock()
        client.beta.files.upload.return_value = mock.Mock(id="file_abc123")

        with mock.patch.object(analytics_agent, "run_agent", side_effect=fake_run_agent):
            result = analytics_agent.run(
                client=client,
                task="Analyze channel performance",
                data_path=str(path),
                questions=["Which channel has the most clicks?"],
            )

        self.assertEqual(result, "## Key Metrics\nok")
        # File was uploaded to the Files API and later deleted.
        client.beta.files.upload.assert_called_once()
        client.beta.files.delete.assert_called_once_with("file_abc123")

        content = captured["user_message"]
        self.assertIsInstance(content, list)
        # A container_upload block references the uploaded file id.
        upload_blocks = [b for b in content if b.get("type") == "container_upload"]
        self.assertEqual(len(upload_blocks), 1)
        self.assertEqual(upload_blocks[0]["file_id"], "file_abc123")

        # The raw data must NOT be inlined into the prompt.
        text_blocks = "\n".join(b.get("text", "") for b in content if b.get("type") == "text")
        self.assertNotIn("linkedin,4999", text_blocks)
        self.assertIn("Analyze channel performance", text_blocks)

        # Code execution tool + Files API beta header are wired up.
        self.assertEqual(captured["tools"][0]["type"], "code_execution_20260120")
        self.assertEqual(captured["extra_headers"], {"anthropic-beta": "files-api-2025-04-14"})

    def test_csv_path_alias_still_accepted(self) -> None:
        path = self._write_temp("data.json", json.dumps([{"a": 1}]).encode("utf-8"))
        client = mock.Mock()
        client.beta.files.upload.return_value = mock.Mock(id="file_xyz")

        with mock.patch.object(analytics_agent, "run_agent", return_value="ok"):
            result = analytics_agent.run(client=client, task="t", csv_path=str(path))

        self.assertEqual(result, "ok")
        client.beta.files.upload.assert_called_once()

    def test_missing_file_returns_error(self) -> None:
        client = mock.Mock()
        result = analytics_agent.run(client=client, task="t", data_path="/no/such/file.csv")
        self.assertIn("not found", result)
        client.beta.files.upload.assert_not_called()


if __name__ == "__main__":
    unittest.main()
