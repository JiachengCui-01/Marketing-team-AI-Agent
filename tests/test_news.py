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

    def test_revert_time_is_next_calendar_day_at_summary_time(self) -> None:
        from datetime import datetime, timezone

        # Cancel at 15:00 UTC — after the 09:00 summary time → next day 09:00.
        after = datetime(2026, 7, 8, 15, 0, tzinfo=timezone.utc).timestamp()
        cfg_after = {**self.config, "cancelled_at": after, "enabled": False}
        self.assertEqual(
            news.cancellation_revert_ts(cfg_after),
            datetime(2026, 7, 9, 9, 0, tzinfo=timezone.utc).timestamp(),
        )

        # Cancel at 07:00 UTC — before the 09:00 summary time → still next day 09:00.
        before = datetime(2026, 7, 8, 7, 0, tzinfo=timezone.utc).timestamp()
        cfg_before = {**self.config, "cancelled_at": before, "enabled": False}
        self.assertEqual(
            news.cancellation_revert_ts(cfg_before),
            datetime(2026, 7, 9, 9, 0, tzinfo=timezone.utc).timestamp(),
        )

    def test_revert_time_respects_timezone(self) -> None:
        from datetime import datetime, timezone
        from zoneinfo import ZoneInfo

        cfg = db.upsert_news_config(
            self.user["id"],
            industry="AI marketing",
            detail_level="brief",
            summary_time="09:00",
            timezone="Asia/Shanghai",
        )
        cancelled_at = datetime(2026, 7, 8, 23, 0, tzinfo=timezone.utc).timestamp()  # 07-09 07:00 CST
        cfg = {**cfg, "cancelled_at": cancelled_at, "enabled": False}
        expected = datetime(2026, 7, 10, 9, 0, tzinfo=ZoneInfo("Asia/Shanghai")).timestamp()
        self.assertEqual(news.cancellation_revert_ts(cfg), expected)

    def test_is_cancel_expired_transitions_at_revert_time(self) -> None:
        cancelled_at = 1_000_000.0
        cfg = {**self.config, "cancelled_at": cancelled_at, "enabled": False}
        revert = news.cancellation_revert_ts(cfg)
        self.assertTrue(news.is_cancelled(cfg))
        self.assertFalse(news.is_cancel_expired(cfg, revert - 1))
        self.assertTrue(news.is_cancel_expired(cfg, revert))
        # An active config is never "cancelled" / expired.
        self.assertFalse(news.is_cancelled(self.config))
        self.assertFalse(news.is_cancel_expired(self.config, revert))

    def test_cancel_news_config_soft_cancels(self) -> None:
        cancelled = db.cancel_news_config(self.user["id"], 1234.5)
        self.assertIsNotNone(cancelled)
        self.assertFalse(cancelled["enabled"])
        self.assertEqual(cancelled["cancelled_at"], 1234.5)
        # Scheduler no longer sees it as an enabled job.
        enabled_ids = {c["user_id"] for c in db.list_enabled_news_configs()}
        self.assertNotIn(self.user["id"], enabled_ids)
        cancelled_ids = {c["user_id"] for c in db.list_cancelled_news_configs()}
        self.assertIn(self.user["id"], cancelled_ids)

    def test_saving_config_reactivates_and_clears_cancellation(self) -> None:
        db.cancel_news_config(self.user["id"], 1234.5)
        reactivated = db.upsert_news_config(
            self.user["id"],
            industry="Fintech",
            detail_level="detailed",
            summary_time="08:00",
            timezone="UTC",
        )
        self.assertTrue(reactivated["enabled"])
        self.assertIsNone(reactivated["cancelled_at"])

    def test_delete_news_data_wipes_config_and_summaries(self) -> None:
        db.add_news_summary(
            self.user["id"], self.config["id"], "## Summary\nx",
            generated_at=1.0, window_start=0.0, window_end=1.0,
        )
        db.delete_news_data(self.user["id"])
        self.assertIsNone(db.get_news_config(self.user["id"]))
        self.assertIsNone(db.get_latest_news_summary(self.user["id"]))


if __name__ == "__main__":
    unittest.main()
