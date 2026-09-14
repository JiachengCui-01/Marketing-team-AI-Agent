"""Job planning and the daily sweep: budget discipline, backoff, and the day lock.

Offline throughout. The vendor is faked at ``sellersprite.call_tool`` and answers
from the captured fixtures, so the jobs exercise the real extractors.
"""
from __future__ import annotations

import json
import os
import pathlib
import unittest
from unittest import mock

from marketing_agent.tools.mcp_client import McpToolError, McpUnavailable
from server import db
from server.market import gateway, jobs, store, sweep, taxonomy

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "sellersprite"
PERIOD = "202608"
BUFFETS = "1055398:1063306:3733781:3733831"


def fixture_vendor(tool: str, arguments: dict) -> str:
    """Answer any tool from its captured reply, falling back to an empty envelope.

    Product replies get their ASINs salted per requested node. The captured fixture
    is one node's reply, and replaying it verbatim for every node would have all
    twelve categories return the same three ASINs — which cannot happen in the real
    marketplace and would make ASIN-to-node attribution untestable.
    """
    path = FIXTURES / f"{tool}.json"
    if not path.exists():
        return '{"code": "OK", "data": []}'
    text = path.read_text(encoding="utf-8")
    if tool != "product_research":
        return text
    node = str((arguments.get("request") or {}).get("nodeIdPath") or "")
    salt = node.rsplit(":", 1)[-1] or "0"
    payload = json.loads(text)
    for index, item in enumerate(payload.get("data", {}).get("items", [])):
        item["asin"] = f"B{salt}{index}"
        item["nodeIdPath"] = node or item.get("nodeIdPath")
    return json.dumps(payload, ensure_ascii=False)


class SweepTestCase(unittest.TestCase):
    def setUp(self) -> None:
        db.reset_for_tests()
        gateway.clear_cache()
        jobs.clear_review_cache()
        self._env = {k: os.environ.get(k) for k in
                     ("MARKETING_AGENT_TEST_LIVE_VENDOR", "SELLERSPRITE_SECRET_KEY",
                      "MARKETING_AGENT_MARKET_SWEEP")}
        os.environ["MARKETING_AGENT_TEST_LIVE_VENDOR"] = "1"
        os.environ["SELLERSPRITE_SECRET_KEY"] = "test-key"
        os.environ["MARKETING_AGENT_MARKET_SWEEP"] = "1"
        self._limits = dict(gateway.DAILY_LIMITS)
        taxonomy.ensure_nodes()

    def tearDown(self) -> None:
        gateway.DAILY_LIMITS.clear()
        gateway.DAILY_LIMITS.update(self._limits)
        for key, value in self._env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        gateway.clear_cache()
        jobs.clear_review_cache()
        db.reset_for_tests()


class PlanningTests(SweepTestCase):
    def test_a_new_month_opens_the_whole_pack(self) -> None:
        planned = jobs.plan_period("US", PERIOD)
        leaves = len(taxonomy.leaf_nodes())
        flagships = len([n for n in taxonomy.leaf_nodes() if n["tier"] == 1])
        per_leaf = len([s for s in jobs.CATALOG
                        if s.scope == "node" and s.tier is None and s.subject_kind == "node"])
        tier1_only = len([s for s in jobs.CATALOG if s.tier == 1])
        department = len([s for s in jobs.CATALOG if s.scope == "department"])
        self.assertEqual(planned,
                         leaves * per_leaf + flagships * tier1_only + department)
        self.assertEqual(store.queue_depth("US"), planned)

    def test_replanning_the_same_month_adds_nothing(self) -> None:
        first = jobs.plan_period("US", PERIOD)
        self.assertEqual(jobs.plan_period("US", PERIOD), 0)
        self.assertEqual(store.queue_depth("US"), first)

    def test_per_asin_jobs_are_not_planned_up_front(self) -> None:
        """The ASINs do not exist until a product pack lands."""
        jobs.plan_period("US", PERIOD)
        kinds = {j["job_kind"] for j in store.due_jobs("US", limit=500)}
        self.assertNotIn("flagship_reviews", kinds)
        self.assertIn("product_pack", kinds)

    def test_structure_jobs_outrank_enrichment(self) -> None:
        """Priority is what makes a half-finished month decision-grade."""
        structure = jobs.BY_KIND["category_structure"].priority
        for kind in ("flagship_reviews", "offamazon_trend", "category_rotating"):
            self.assertGreater(jobs.BY_KIND[kind].priority, structure)


class JobExecutionTests(SweepTestCase):
    def _job(self, kind: str, subject_id: str = BUFFETS, period: str = PERIOD) -> dict:
        store.enqueue_job(marketplace="US", job_kind=kind,
                          subject_kind=jobs.BY_KIND[kind].subject_kind,
                          subject_id=subject_id, period=period,
                          est_calls=jobs.BY_KIND[kind].est_calls)
        return next(j for j in store.due_jobs("US", limit=500) if j["job_kind"] == kind)

    def test_category_structure_lands_the_scoring_inputs(self) -> None:
        with mock.patch.object(gateway.sellersprite, "call_tool", side_effect=fixture_vendor):
            result = jobs.run_job(self._job("category_structure"))
        self.assertEqual(result.status, "done")
        snap = store.get_node_snapshot("US", BUFFETS, PERIOD)
        self.assertAlmostEqual(snap["avg_price"], 186.91)
        self.assertAlmostEqual(snap["top5_brand_crn"], 0.3929)
        self.assertAlmostEqual(snap["return_ratio"], 0.015674)
        self.assertAlmostEqual(snap["hl_avg_price"], 151.11)  # from statistics

    def test_a_half_empty_structure_job_is_not_called_done(self) -> None:
        """The production failure this came from: ``market_research`` returned no
        rows for a month still in progress, statistics answered normally, and the
        job reported success. Nothing retried it, ``node_completeness`` read 100%,
        and every board row scored on 27% of its weight for the rest of the month.
        """
        def half(tool: str, arguments: dict) -> str:
            if tool == "market_research":
                return '{"code": "OK", "data": {"items": [], "total": 0}}'
            return fixture_vendor(tool, arguments)

        with mock.patch.object(gateway.sellersprite, "call_tool", side_effect=half):
            result = jobs.run_job(self._job("category_structure"))
        self.assertEqual(result.status, "pending")
        self.assertIn("market_research", result.detail)

        # The half that did land is kept — it cost money and it is still true.
        snap = store.get_node_snapshot("US", BUFFETS, PERIOD)
        self.assertAlmostEqual(snap["hl_avg_price"], 151.11)
        self.assertIsNone(snap["total_revenue"])

        # And the node is not reported as fully collected.
        completeness, missing = jobs.node_completeness("US", BUFFETS, PERIOD)
        self.assertLess(completeness, 1.0)
        self.assertIn("category_structure", missing)

    def test_a_board_with_no_revenue_says_so_instead_of_printing_zero(self) -> None:
        """Summing ``or 0.0`` over absent values states a measurement of $0."""
        from server.market import panels
        store.upsert_node_snapshot("US", BUFFETS, PERIOD, {"avg_price": 186.91})
        board = panels.build_overview("US", PERIOD, "zh")
        revenue = next(k for k in board["headline"]["kpis"] if "销售额" in k["label"])
        returns = next(k for k in board["headline"]["kpis"] if "退货" in k["label"])
        self.assertEqual(revenue["value"], "—")
        self.assertTrue(revenue["hint"])
        self.assertEqual(returns["value"], "—")

    def test_category_structure_records_evidence_for_every_metric(self) -> None:
        with mock.patch.object(gateway.sellersprite, "call_tool", side_effect=fixture_vendor):
            jobs.run_job(self._job("category_structure"))
        rows = store.evidence_for("US", [("node", BUFFETS)], PERIOD)
        metrics = {r["metric"] for r in rows}
        self.assertIn("avg_price", metrics)
        self.assertIn("return_ratio", metrics)
        self.assertTrue(all(r["tool"] for r in rows))
        self.assertTrue(all(r["field_path"] for r in rows))

    def test_demand_job_writes_the_trend_series_into_its_own_months(self) -> None:
        with mock.patch.object(gateway.sellersprite, "call_tool", side_effect=fixture_vendor):
            jobs.run_job(self._job("category_demand"))
        history = store.snapshot_history("US", BUFFETS)
        self.assertGreater(len(history), 1)
        self.assertTrue(any(p["glance_views"] for p in history))

    def test_product_pack_enqueues_per_asin_work_for_a_flagship(self) -> None:
        with mock.patch.object(gateway.sellersprite, "call_tool", side_effect=fixture_vendor):
            result = jobs.run_job(self._job("product_pack"))
        self.assertEqual(result.status, "done")
        self.assertGreater(result.followups, 0)
        kinds = {j["job_kind"] for j in store.due_jobs("US", limit=500)}
        self.assertIn("flagship_reviews", kinds)

    def test_a_tier_two_product_pack_enqueues_nothing_expensive(self) -> None:
        tier2 = next(n for n in taxonomy.leaf_nodes() if n["tier"] == 2)
        with mock.patch.object(gateway.sellersprite, "call_tool", side_effect=fixture_vendor):
            result = jobs.run_job(self._job("product_pack", tier2["node_id_path"]))
        self.assertEqual(result.followups, 0)

    def test_review_prose_is_held_in_process_not_persisted(self) -> None:
        """Third-party text has no analytical value once themed, and it would
        dominate the database."""
        asin = "B0F5WV3394"  # any ASIN; the review fixture is not salted
        with mock.patch.object(gateway.sellersprite, "call_tool", side_effect=fixture_vendor):
            jobs.run_job(self._job("flagship_reviews", asin))
        self.assertTrue(jobs.cached_reviews("US", asin, PERIOD))
        with db.connect() as conn:
            tables = [r["name"] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%review%'")]
        self.assertEqual(tables, ["market_review_themes"])

    def test_a_vendor_rejection_backs_off_and_stays_billable(self) -> None:
        job = self._job("category_brands")
        with mock.patch.object(gateway.sellersprite, "call_tool",
                               side_effect=McpToolError("endpoint not in your plan")):
            result = jobs.run_job(job)
        self.assertEqual(result.status, "pending")
        with db.connect() as conn:
            row = conn.execute("SELECT attempts, next_due_at, status FROM market_jobs "
                               "WHERE id = ?", (job["id"],)).fetchone()
        self.assertEqual(row["attempts"], 1)
        self.assertEqual(row["status"], "pending")
        self.assertGreater(row["next_due_at"], gateway.sweep_now().timestamp())
        self.assertEqual(store.calls_used("US", gateway.run_date()), 1)  # charged

    def test_three_refusals_become_a_declared_gap(self) -> None:
        job = self._job("category_brands")
        with mock.patch.object(gateway.sellersprite, "call_tool",
                               side_effect=McpToolError("nope")):
            for _ in range(jobs.MAX_ATTEMPTS):
                current = next((j for j in store.due_jobs("US", limit=500,
                                                          now=2 ** 31)
                                if j["id"] == job["id"]), None)
                if current is None:
                    break
                jobs.run_job(current)
        with db.connect() as conn:
            row = conn.execute("SELECT status FROM market_jobs WHERE id = ?",
                               (job["id"],)).fetchone()
        self.assertEqual(row["status"], "blocked")

    def test_an_unknown_job_kind_is_blocked_not_crashed(self) -> None:
        store.enqueue_job(marketplace="US", job_kind="not_a_job", subject_kind="node",
                          subject_id=BUFFETS, period=PERIOD)
        job = next(j for j in store.due_jobs("US", limit=500)
                   if j["job_kind"] == "not_a_job")
        self.assertEqual(jobs.run_job(job).status, "blocked")

    def test_node_completeness_reads_the_queue(self) -> None:
        with mock.patch.object(gateway.sellersprite, "call_tool", side_effect=fixture_vendor):
            jobs.run_job(self._job("category_structure"))
        score, missing = jobs.node_completeness("US", BUFFETS, PERIOD)
        self.assertGreater(score, 0.0)
        self.assertLess(score, 1.0)
        self.assertIn("category_brands", missing)


class SweepTests(SweepTestCase):
    def test_the_cap_stops_the_sweep_and_leaves_the_rest_queued(self) -> None:
        gateway.DAILY_LIMITS[gateway.BUCKET_SWEEP] = 10
        with mock.patch.object(gateway.sellersprite, "call_tool", side_effect=fixture_vendor):
            summary = sweep.run_daily_sweep("US")
        self.assertEqual(summary["status"], "budget_exhausted")
        self.assertLessEqual(summary["calls_used"], 10)
        self.assertGreater(summary["queue_depth"], 0)

    def test_a_two_call_job_never_starts_with_one_call_left(self) -> None:
        """A half-ingested job is the one failure that leaves the warehouse wrong."""
        gateway.DAILY_LIMITS[gateway.BUCKET_SWEEP] = 3
        with mock.patch.object(gateway.sellersprite, "call_tool", side_effect=fixture_vendor):
            summary = sweep.run_daily_sweep("US")
        self.assertLessEqual(summary["calls_used"], 3)

    def test_only_one_worker_claims_the_day(self) -> None:
        gateway.DAILY_LIMITS[gateway.BUCKET_SWEEP] = 2
        with mock.patch.object(gateway.sellersprite, "call_tool", side_effect=fixture_vendor):
            first = sweep.run_daily_sweep("US")
            second = sweep.run_daily_sweep("US")
        self.assertNotEqual(first["status"], "claimed_elsewhere")
        self.assertEqual(second["status"], "claimed_elsewhere")
        with db.connect() as conn:
            count = conn.execute("SELECT COUNT(*) AS n FROM market_runs").fetchone()["n"]
        self.assertEqual(count, 1)

    def test_a_transport_outage_aborts_without_spending_or_penalising_jobs(self) -> None:
        gateway.DAILY_LIMITS[gateway.BUCKET_SWEEP] = 20
        with mock.patch.object(gateway.sellersprite, "call_tool",
                               side_effect=McpUnavailable("connection reset")):
            summary = sweep.run_daily_sweep("US")
        self.assertEqual(summary["status"], "aborted")
        self.assertEqual(summary["calls_used"], 0)
        with db.connect() as conn:
            attempts = [r["attempts"] for r in conn.execute(
                "SELECT attempts FROM market_jobs")]
        self.assertTrue(all(a == 0 for a in attempts))

    def test_the_sweep_is_a_no_op_when_switched_off(self) -> None:
        os.environ["MARKETING_AGENT_MARKET_SWEEP"] = "0"
        with mock.patch.object(gateway.sellersprite, "call_tool") as vendor:
            self.assertEqual(sweep.run_daily_sweep("US")["status"], "disabled")
        vendor.assert_not_called()
        self.assertFalse(sweep.is_due("US"))

    def test_a_zero_budget_sweep_makes_no_calls(self) -> None:
        gateway.DAILY_LIMITS[gateway.BUCKET_SWEEP] = 0
        with mock.patch.object(gateway.sellersprite, "call_tool") as vendor:
            self.assertEqual(sweep.run_daily_sweep("US")["status"], "no_budget")
        vendor.assert_not_called()

    def test_an_unconfigured_vendor_is_a_no_op(self) -> None:
        os.environ["SELLERSPRITE_SECRET_KEY"] = ""
        with mock.patch.object(gateway.sellersprite, "call_tool") as vendor:
            self.assertEqual(sweep.run_daily_sweep("US")["status"], "unconfigured")
        vendor.assert_not_called()

    def test_is_due_is_false_once_the_day_is_claimed(self) -> None:
        gateway.DAILY_LIMITS[gateway.BUCKET_SWEEP] = 1
        self.assertTrue(sweep.is_due("US"))
        with mock.patch.object(gateway.sellersprite, "call_tool", side_effect=fixture_vendor):
            sweep.run_daily_sweep("US")
        self.assertFalse(sweep.is_due("US"))

    def test_the_sweep_only_ever_collects_a_closed_month(self) -> None:
        """``market_research`` is a monthly aggregate and the vendor publishes it
        once the month has ended; asked for a month in progress it returns no rows
        at all. Targeting the current month left the board holding only the live
        listing snapshot: $0 revenue and an evidence coverage of 0.27."""
        from datetime import datetime
        from zoneinfo import ZoneInfo
        tz = ZoneInfo("America/Los_Angeles")
        for day in (1, 2, 6, 15, 20, 28):
            with self.subTest(day=day):
                self.assertEqual(
                    sweep.target_period(datetime(2026, 9, day, tzinfo=tz)), "202608")
        # And it rolls over on the 1st, not mid-month.
        self.assertEqual(sweep.target_period(datetime(2026, 10, 1, tzinfo=tz)), "202609")
        self.assertEqual(sweep.target_period(datetime(2026, 1, 3, tzinfo=tz)), "202512")

    def test_a_full_sweep_fills_a_node_end_to_end(self) -> None:
        gateway.DAILY_LIMITS[gateway.BUCKET_SWEEP] = 200
        with mock.patch.object(gateway.sellersprite, "call_tool", side_effect=fixture_vendor):
            summary = sweep.run_daily_sweep("US")
        self.assertEqual(summary["status"], "complete")
        snap = store.get_node_snapshot("US", BUFFETS, summary["period"])
        self.assertIsNotNone(snap)
        self.assertTrue(store.get_distribution("US", BUFFETS, summary["period"], "price"))
        self.assertTrue(store.get_concentration("US", BUFFETS, summary["period"], "brand"))
        self.assertTrue(store.top_products("US", BUFFETS, summary["period"]))


if __name__ == "__main__":
    unittest.main()
