from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest import mock

from server import db, news
from marketing_agent.agents import research_agent
from marketing_agent.tools import product_browser, web_search


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

    def test_research_exposes_the_client_side_fallback_tools(self) -> None:
        # DeepSeek has no server-side search, so the agent carries its own tool.
        # These are the fallback pair; the primary source is discovered from
        # SellerSprite's MCP server at call time.
        self.assertEqual(research_agent.FALLBACK_TOOLS[0]["name"], "web_search")
        self.assertEqual(research_agent.FALLBACK_TOOLS[1]["name"], "browse_product_page")
        self.assertIn("query", research_agent.FALLBACK_TOOLS[0]["input_schema"]["properties"])
        self.assertIn("url", research_agent.FALLBACK_TOOLS[1]["input_schema"]["properties"])
        self.assertIn("never run more than", research_agent.SYSTEM.lower())
        self.assertIn("untrusted evidence", research_agent.SYSTEM.lower())
        self.assertIn("at least two distinct collected reviews", research_agent.SYSTEM.lower())

    def test_research_prompt_ranks_sellersprite_as_the_primary_source(self) -> None:
        system = research_agent.SYSTEM
        self.assertIn("SellerSprite (卖家精灵) is the primary source", system)
        self.assertIn("web_search is the fallback", system)
        self.assertIn("browse_product_page is the fallback", system)
        # Estimated vendor figures must never be presented as measurements.
        self.assertIn("MODELED ESTIMATES", system)
        # The primary source must sort before the fallbacks in the hierarchy.
        self.assertLess(system.find("primary source"), system.find("is the fallback"))

    def test_research_unavailable_without_a_search_provider(self) -> None:
        with mock.patch.object(web_search, "is_available", return_value=False):
            result = research_agent.run(
                mock.Mock(), task="t", topics=["US furniture retail"], response_language="en"
            )
        self.assertIn("## Research Unavailable", result)
        self.assertIn("TAVILY_API_KEY", result)

    def test_research_prompt_and_output_include_source_tiers(self) -> None:
        self.assertIn("Tier 1", research_agent.SYSTEM)
        self.assertIn("Do not move citations into a standalone Sources section", research_agent.SYSTEM)
        self.assertIn("Do not add a final raw URL list", research_agent.SYSTEM)

        answer = (
            "## Summary\nSignal.\n\n"
            "## Sources\n"
            "1. https://www.reuters.com/business/\n"
            "2. https://www.reddit.com/r/furniture/comments/1"
        )
        with mock.patch.object(web_search, "is_available", return_value=True), \
                mock.patch.object(research_agent, "run_agent", return_value=answer):
            result = research_agent.run(
                mock.Mock(),
                task="Research US furniture demand",
                topics=["US furniture retail"],
                response_language="en",
            )

        self.assertIn("## Source Credibility", result)
        self.assertNotIn("## Sources", result)
        self.assertLess(result.find("reuters.com"), result.find("reddit.com"))
        self.assertIn("Tier 4", result)

    def test_research_wires_search_results_into_the_tool_handler(self) -> None:
        captured: dict = {}

        def fake_run_agent(**kwargs):
            captured.update(kwargs)
            return "## Summary\nFinding [Furniture Today](https://www.furnituretoday.com/x)"

        results = [
            web_search.SearchResult(
                title="Furniture Today",
                url="https://www.furnituretoday.com/x",
                snippet="US furniture demand steady.",
                published="2026-08-01",
            )
        ]
        with mock.patch.object(web_search, "is_available", return_value=True), \
                mock.patch.object(research_agent, "run_agent", side_effect=fake_run_agent), \
                mock.patch.object(web_search, "search", return_value=results):
            result = research_agent.run(
                mock.Mock(),
                task="Research US furniture demand",
                topics=["US furniture retail"],
                response_language="en",
            )
            # The tool handler surfaces real search results to the model.
            tool_output = captured["client_tool_handlers"]["web_search"](
                {"query": "US furniture retail"}
            )

        self.assertIn("https://www.furnituretoday.com/x", tool_output)
        self.assertIn("2026-08-01", tool_output)

        # Inline citations the model wrote still get source-tier annotation.
        self.assertIn("[Furniture Today](https://www.furnituretoday.com/x)", result)
        self.assertIn("## Source Credibility", result)
        self.assertIn("Tier 2", result)

    def test_research_only_browses_urls_returned_by_search(self) -> None:
        captured: dict = {}

        def fake_run_agent(**kwargs):
            captured.update(kwargs)
            return "## Summary\nBrowser-verified finding [Product](https://shop.example.com/p/sofa)"

        results = [
            web_search.SearchResult(
                title="Product",
                url="https://shop.example.com/p/sofa",
                snippet="A product page.",
            )
        ]
        browser_result = {
            "source_type": "live_browser",
            "final_url": results[0].url,
            "product": {"price": "999", "currency": "USD"},
            "reviews": ["Assembly instructions were unclear."],
        }
        with mock.patch.object(web_search, "is_available", return_value=True), \
                mock.patch.object(research_agent, "run_agent", side_effect=fake_run_agent), \
                mock.patch.object(web_search, "search", return_value=results), \
                mock.patch.object(product_browser, "browse_product_page", return_value=browser_result):
            research_agent.run(
                mock.Mock(),
                task="Compare sofas",
                topics=["sofas"],
                response_language="en",
            )
            handlers = captured["client_tool_handlers"]
            denied = handlers["browse_product_page"]({"url": "https://other.example.com/p/1"})
            search_output = handlers["web_search"]({"query": "comparable sofas"})
            browsed = handlers["browse_product_page"]({"url": results[0].url})

        self.assertIn(results[0].url, search_output)
        self.assertIn("only open an exact URL", denied)
        self.assertIn("BEGIN UNTRUSTED BROWSER EVIDENCE", browsed)
        self.assertIn('"source_type": "live_browser"', browsed)
        self.assertIn("Assembly instructions were unclear", browsed)

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
        self.assertIn("Chinese and China-local sources", zh_task)

    def test_build_task_requests_chinese_sources_for_china_topic(self) -> None:
        from datetime import datetime, timezone

        task, _, _ = news.build_task(
            "China EV marketing", "brief", datetime.now(timezone.utc), "en"
        )

        self.assertIn("Chinese and China-local sources", task)
        self.assertIn("Xinhua", task)

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
        digest = "## Summary\nFresh news.\n\n## Sources\n1. https://www.sec.gov/news"
        with mock.patch.object(research_agent, "run", return_value=digest):
            record = news.generate_summary(self.config, client=mock.Mock())

        self.assertIn("## 来源可信度", record["summary"])
        self.assertNotIn("## Sources", record["summary"])
        self.assertEqual(record["sources"][0]["domain"], "sec.gov")
        self.assertEqual(record["sources"][0]["tier"], 1)
        self.assertEqual(record["strong_source_count"], 1)
        self.assertEqual(record["weak_source_count"], 0)
        self.assertIsNotNone(db.get_news_config(self.user["id"])["last_run_at"])

    def test_weak_only_news_is_marked_uncertain(self) -> None:
        digest = "## Summary\nMarket discussion.\n\n## Sources\n1. https://www.reddit.com/r/marketing/comments/1"
        with mock.patch.object(research_agent, "run", return_value=digest):
            record = news.generate_summary(self.config, client=mock.Mock())

        self.assertIn("弱信号", record["summary"])
        self.assertEqual(record["strong_source_count"], 0)
        self.assertEqual(record["weak_source_count"], 1)
        self.assertEqual(record["sources"][0]["tier"], 4)

    def test_news_sources_are_persisted_and_returned(self) -> None:
        record = db.add_news_summary(
            self.user["id"],
            self.config["id"],
            "## Summary\nx",
            generated_at=1.0,
            window_start=0.0,
            window_end=1.0,
            sources=[
                {
                    "url": "https://www.reuters.com/world/",
                    "domain": "reuters.com",
                    "tier": 2,
                    "tier_label": "Tier 2 - authoritative media / official website",
                    "score": 80,
                    "reason": "Recognized media",
                    "is_weak_signal": False,
                }
            ],
            source_score=80,
            strong_source_count=1,
            weak_source_count=0,
        )

        latest = db.get_latest_news_summary(self.user["id"])

        self.assertEqual(latest["id"], record["id"])
        self.assertEqual(latest["source_score"], 80)
        self.assertEqual(latest["sources"][0]["domain"], "reuters.com")

    def test_news_summary_source_columns_migrate_from_old_schema(self) -> None:
        db.reset_for_tests()
        with db._connect() as conn:  # type: ignore[attr-defined]
            conn.execute(
                "CREATE TABLE news_summaries ("
                "id TEXT PRIMARY KEY, user_id TEXT NOT NULL, config_id TEXT, "
                "summary TEXT NOT NULL, generated_at REAL NOT NULL, window_start REAL, "
                "window_end REAL, created_at REAL NOT NULL)"
            )

        db.init()

        with db._connect() as conn:  # type: ignore[attr-defined]
            cols = db._table_columns(conn, "news_summaries")  # type: ignore[attr-defined]
        self.assertIn("sources_json", cols)
        self.assertIn("source_score", cols)
        self.assertIn("strong_source_count", cols)
        self.assertIn("weak_source_count", cols)

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


    def test_generate_summary_without_a_client_uses_the_shared_one(self) -> None:
        """The background scheduler calls generate_summary(config) with no client.

        That path used to raise NameError, because the module referenced a client
        factory it never imported — so the nightly job died silently.
        """
        digest = "## Summary\nUS furniture demand steady [Furniture Today](https://www.furnituretoday.com/x)"
        with mock.patch.object(news.llm, "get_client", return_value=mock.Mock()) as get_client, \
                mock.patch.object(news.research_agent, "run", return_value=digest):
            record = news.generate_summary(self.config)

        get_client.assert_called_once()
        self.assertIn("## Summary", record["summary"])

    def test_generate_summary_without_a_key_raises_a_readable_error(self) -> None:
        with mock.patch.object(news.llm, "get_client", return_value=None):
            with self.assertRaises(news.NewsGenerationError):
                news.generate_summary(self.config)

    def test_us_furniture_sources_are_requested_for_english_topics(self) -> None:
        task, _, _ = news.build_task(
            "US furniture retail", "brief", datetime.now(timezone.utc), "en"
        )
        self.assertIn("Furniture Today", task)
        self.assertIn("CPSC", task)


if __name__ == "__main__":
    unittest.main()
