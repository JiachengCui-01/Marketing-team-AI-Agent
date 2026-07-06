from __future__ import annotations

import unittest
from unittest import mock

from server import db, news
from marketing_agent.agents import research_agent


class NewsTests(unittest.TestCase):
    def setUp(self) -> None:
        db.reset_for_tests()
        self.user = db.create_user(
            account="news@example.com",
            password_hash="hash",
            username="News",
            real_name="Test User",
            id_card="11010519491231002X",
        )
        self.config = db.upsert_news_config(
            self.user["id"],
            industry="AI marketing",
            detail_level="brief",
            summary_time="09:00",
            timezone="UTC",
        )

    def tearDown(self) -> None:
        db.reset_for_tests()

    def test_research_uses_three_basic_searches(self) -> None:
        self.assertEqual(research_agent.TOOLS[0]["type"], "web_search_20250305")
        self.assertEqual(research_agent.TOOLS[0]["max_uses"], 3)

    def test_build_task_uses_requested_language(self) -> None:
        from datetime import datetime, timezone

        zh_task, _, _ = news.build_task(
            "AI marketing", "brief", datetime.now(timezone.utc), "zh"
        )
        en_task, _, _ = news.build_task(
            "AI marketing", "brief", datetime.now(timezone.utc), "en"
        )

        self.assertIn("Simplified Chinese", zh_task)
        self.assertIn("entire response in English", en_task)

    def test_chinese_digest_removes_english_search_preamble(self) -> None:
        raw = "I'll search first.\n\n## 摘要\n这是中文摘要。\n\n## 来源\n1. 示例"
        self.assertEqual(
            news._trim_search_preamble(raw, "zh"),
            "## 摘要\n这是中文摘要。\n\n## 来源\n1. 示例",
        )

    def test_failed_research_does_not_replace_last_good_summary(self) -> None:
        previous = db.add_news_summary(
            self.user["id"],
            self.config["id"],
            "## Summary\nA valid earlier digest.",
            generated_at=1.0,
            window_start=0.0,
            window_end=1.0,
        )

        failed = (
            "I wasn't able to complete a usable search because the search-tool "
            "limit was reached.\n\n## Sources\nNone."
        )
        with mock.patch.object(research_agent, "run", return_value=failed):
            with self.assertRaises(news.NewsGenerationError):
                news.generate_summary(self.config, client=mock.Mock())

        latest = db.get_latest_news_summary(self.user["id"])
        self.assertEqual(latest["id"], previous["id"])
        self.assertIsNone(db.get_news_config(self.user["id"])["last_run_at"])

    def test_successful_research_is_persisted(self) -> None:
        digest = "## Summary\nFresh news.\n\n## Sources\n1. https://example.com/news"
        with mock.patch.object(research_agent, "run", return_value=digest):
            record = news.generate_summary(self.config, client=mock.Mock())

        self.assertEqual(record["summary"], digest)
        self.assertIsNotNone(db.get_news_config(self.user["id"])["last_run_at"])


if __name__ == "__main__":
    unittest.main()
