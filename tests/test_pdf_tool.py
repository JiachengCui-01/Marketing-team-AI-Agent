from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from marketing_agent.tools import pdf_tool


class PdfToolTests(unittest.TestCase):
    def test_generate_pdf_accepts_chinese_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(pdf_tool, "ARTIFACTS_DIR", Path(tmp)):
                result = pdf_tool.generate_pdf(
                    {
                        "title": "中文营销方案",
                        "subtitle": "小红书内容规划",
                        "sections": [
                            {
                                "heading": "目标人群",
                                "body": "面向年轻消费者，突出真实体验、使用场景和购买理由。",
                            }
                        ],
                    }
                )
                self.assertTrue(Path(result["path"]).exists())

        self.assertEqual(result["mime"], "application/pdf")
        self.assertTrue(result["filename"].endswith(".pdf"))
