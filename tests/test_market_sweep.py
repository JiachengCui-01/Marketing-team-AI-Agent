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
from server.market import gateway, jobs, scoring, store, sweep, taxonomy

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
        # The pulse is weekly and keyed by week, so plan_pulse owns it.
        per_leaf = len([s for s in jobs.CATALOG
                        if s.scope == "node" and s.tier is None
                        and s.subject_kind == "node" and s.kind not in jobs.PULSE_KINDS])
        tier1_only = len([s for s in jobs.CATALOG if s.tier == 1])
        department = len([s for s in jobs.CATALOG if s.scope == "department"])
        self.assertEqual(planned,
                         leaves * per_leaf + flagships * tier1_only + department)
        self.assertEqual(store.queue_depth("US"), planned)

    def test_the_monthly_plan_never_queues_a_pulse(self) -> None:
        """Keyed by month, a weekly job would collide with its own first run."""
        jobs.plan_period("US", PERIOD)
        self.assertEqual([j for j in store.due_jobs("US", limit=500)
                          if j["job_kind"] in jobs.PULSE_KINDS], [])

    def test_the_pulse_is_planned_once_per_week_per_node(self) -> None:
        added = jobs.plan_pulse("US")
        self.assertEqual(added, len(taxonomy.leaf_nodes()))
        self.assertEqual(jobs.plan_pulse("US"), 0)      # same week, idempotent
        queued = [j for j in store.due_jobs("US", limit=500)
                  if j["job_kind"] == "category_pulse"]
        self.assertEqual({j["period"] for j in queued}, {jobs.week_stamp()})

    def test_a_new_week_reopens_the_pulse(self) -> None:
        from datetime import datetime, timedelta
        from zoneinfo import ZoneInfo
        tz = ZoneInfo("America/Los_Angeles")
        now = datetime(2026, 9, 10, tzinfo=tz)
        jobs.plan_pulse("US", now)
        self.assertEqual(jobs.plan_pulse("US", now + timedelta(days=7)),
                         len(taxonomy.leaf_nodes()))

    def test_the_pulse_is_not_parked_for_targeting_the_open_month(self) -> None:
        """Parking it would retire the only view of the month in progress."""
        jobs.plan_pulse("US")
        parked = store.park_future_jobs("US", "202608", exempt_kinds=jobs.PULSE_KINDS)
        self.assertEqual(parked, 0)
        self.assertTrue([j for j in store.due_jobs("US", limit=500)
                         if j["job_kind"] == "category_pulse"])

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
        for kind in ("flagship_reviews", "offamazon_trend", "category_dist_rating",
                     "category_conc_seller"):
            self.assertGreater(jobs.BY_KIND[kind].priority, structure)

    def test_every_structural_distribution_runs_for_every_node(self) -> None:
        """A rotating slot makes each month a different shape, so the one thing
        the structure section cannot show is a change."""
        jobs.plan_period("US", PERIOD)
        queued = store.due_jobs("US", limit=1000)
        leaves = len(taxonomy.leaf_nodes())
        for kind in ("category_dist_rating", "category_dist_ratings_count",
                     "category_dist_ebc", "category_dist_seller_country",
                     "category_conc_seller", "category_conc_seller_type",
                     "category_conc_product"):
            with self.subTest(kind=kind):
                self.assertEqual(len([j for j in queued if j["job_kind"] == kind]),
                                 leaves)


class EnrolmentTests(SweepTestCase):
    """The monthly walk enrols what it finds, instead of recording and ignoring it.

    ``_department_roll`` always listed each department root's children and wrote a
    snapshot per child — and then marked every one ``tracked=False`` unless it was
    in the hand-listed catalog. So the board stayed at twelve categories while the
    warehouse knew about forty.
    """

    def _job(self, kind: str, subject_id: str = "", period: str = PERIOD) -> dict:
        spec = jobs.BY_KIND[kind]
        store.enqueue_job(marketplace="US", job_kind=kind,
                          subject_kind=spec.subject_kind,
                          subject_id=subject_id or taxonomy.FURNITURE_ROOT,
                          period=period, est_calls=spec.est_calls)
        return next(j for j in store.due_jobs("US", limit=500) if j["job_kind"] == kind)

    def roll(self, rows: list[dict]) -> None:
        payload = json.dumps({"code": "OK", "data": {"items": rows}})

        def vendor(tool: str, arguments: dict) -> str:
            return payload if tool == "market_research" else fixture_vendor(tool, arguments)

        with mock.patch.object(gateway.sellersprite, "call_tool", side_effect=vendor):
            jobs.run_job(self._job("department_roll"))

    def node(self, path: str, label: str, products: float) -> dict:
        return {"nodeIdPath": path, "nodeLabelPath": label, "totalProducts": products,
                "totalRevenue": 1_000_000.0, "avgPrice": 200.0}

    def test_a_discovered_category_becomes_a_board_row(self) -> None:
        path = "1055398:1063306:1063308:3733321"
        self.roll([self.node(path, "Home & Kitchen:Furniture:Bedroom Furniture:Dressers",
                             9_000.0)])
        tracked = {n["node_id_path"] for n in taxonomy.tracked_nodes()}
        self.assertIn(path, tracked)
        self.assertIn(path, {n["node_id_path"] for n in taxonomy.leaf_nodes()})

    def test_a_category_too_small_to_repay_a_pack_is_recorded_not_enrolled(self) -> None:
        path = "1055398:1063306:1063308:9999901"
        self.roll([self.node(path, "Home & Kitchen:Furniture:Bedroom Furniture:Bed Rails",
                             12.0)])
        self.assertNotIn(path, {n["node_id_path"] for n in taxonomy.tracked_nodes()})
        # Recorded, so next month's walk does not have to rediscover it.
        self.assertIsNotNone(store.get_node("US", path))

    def test_the_other_departments_are_in_scope_now(self) -> None:
        """Patio, office seating and pet beds sit outside Home & Kitchen, which is
        what made them invisible."""
        patio = "2972638011:553824:3480731"
        office = "1064954:1069102:1069104"
        self.roll([
            self.node(patio, "Patio, Lawn & Garden:Patio Furniture & Accessories:"
                             "Patio Seating", 14_000.0),
            self.node(office, "Office Products:Office Furniture & Lighting:Chairs",
                      11_000.0),
        ])
        tracked = {n["node_id_path"] for n in taxonomy.tracked_nodes()}
        self.assertIn(patio, tracked)
        self.assertIn(office, tracked)

    def test_out_of_scope_rows_are_ignored_entirely(self) -> None:
        self.roll([self.node("1:2:3", "Grocery:Paper Goods:Napkins", 90_000.0)])
        self.assertNotIn("1:2:3", {n["node_id_path"] for n in taxonomy.tracked_nodes()})

    def test_the_walk_covers_every_department_root(self) -> None:
        seen: list[str] = []

        def vendor(tool: str, arguments: dict) -> str:
            if tool == "market_research":
                seen.append(str((arguments.get("request") or {}).get("nodeIdPath")))
                return json.dumps({"code": "OK", "data": {"items": []}})
            return fixture_vendor(tool, arguments)

        with mock.patch.object(gateway.sellersprite, "call_tool", side_effect=vendor):
            jobs.run_job(self._job("department_roll"))
        # A set, not a sequence: the gateway retries an empty reply once without
        # returnFields, so each root legitimately appears twice here.
        self.assertEqual(set(seen), set(taxonomy.AREA_ROOTS))

    def test_the_tracked_set_is_capped_so_a_month_can_still_finish(self) -> None:
        """Each tracked node costs roughly two dozen calls a month; an unbounded
        walk enrols faster than the budget can collect."""
        rows = [self.node(f"1055398:1063306:1063318:90000{i:02d}",
                          f"Home & Kitchen:Furniture:Living Room Furniture:Cat {i}",
                          float(1_000 + i))
                for i in range(80)]
        self.roll(rows)
        tracked = taxonomy.tracked_nodes()
        self.assertLessEqual(len(tracked), taxonomy.MAX_TRACKED_NODES)
        # The catalog survives the cap whatever its size.
        kept = {n["node_id_path"] for n in tracked}
        for path in taxonomy.TRACKED_PATHS:
            with self.subTest(path=path):
                self.assertIn(path, kept)

    def test_the_cap_drops_the_smallest_first(self) -> None:
        store.upsert_nodes([
            {"marketplace": "US", "node_id_path": f"x:{i}",
             "node_label_path": f"Home & Kitchen:Furniture:Cat {i}",
             "tracked": True, "tier": 2, "products": float(i)}
            for i in range(1, 6)])
        store.cap_tracked_nodes("US", len(taxonomy.TRACKED_PATHS) + 2,
                                keep=taxonomy.TRACKED_PATHS)
        kept = {n["node_id_path"] for n in taxonomy.tracked_nodes()}
        self.assertIn("x:5", kept)
        self.assertIn("x:4", kept)
        self.assertNotIn("x:1", kept)


class ListingDepthTests(SweepTestCase):
    """The pull stops when a page stops moving the number, not after three pages.

    Three pages was 150 listings out of a category's several thousand, which made
    the summed revenue figure a reading of the head and nothing else.
    """

    def _job(self, kind: str, subject_id: str = BUFFETS, period: str = PERIOD) -> dict:
        store.enqueue_job(marketplace="US", job_kind=kind,
                          subject_kind=jobs.BY_KIND[kind].subject_kind,
                          subject_id=subject_id, period=period,
                          est_calls=jobs.BY_KIND[kind].est_calls)
        return next(j for j in store.due_jobs("US", limit=500) if j["job_kind"] == kind)

    def test_the_cap_is_deep_enough_to_pass_the_head(self) -> None:
        self.assertGreaterEqual(jobs.PRODUCT_PAGES * 50, 1_000)

    def test_a_short_category_costs_one_call_not_the_cap(self) -> None:
        """The fixture returns fewer rows than a full page, so the vendor is out."""
        with mock.patch.object(gateway.sellersprite, "call_tool",
                               side_effect=fixture_vendor):
            result = jobs.run_job(self._job("product_pack"))
        self.assertEqual(result.status, "done")
        self.assertEqual(result.calls, 1)

    def test_an_exhausted_category_records_a_zero_tail(self) -> None:
        with mock.patch.object(gateway.sellersprite, "call_tool",
                               side_effect=fixture_vendor):
            jobs.run_job(self._job("product_pack"))
        snap = store.get_node_snapshot("US", BUFFETS, PERIOD)
        self.assertEqual(snap["product_tail_pct"], 0.0)

    def test_paging_stops_once_a_page_stops_paying(self) -> None:
        """A full page every time, with revenue decaying — the loop must not run
        to the cap just because the vendor keeps answering."""
        page = {"code": "OK", "data": {"total": 9_999, "items": [
            {"asin": f"B{i:04d}", "title": f"Listing {i}", "price": 100.0,
             "revenue": 1.0, "units": 1.0}
            for i in range(jobs.PRODUCT_PAGE_SIZE)]}}
        first = {"code": "OK", "data": {"total": 9_999, "items": [
            {"asin": f"A{i:04d}", "title": f"Head {i}", "price": 400.0,
             "revenue": 100_000.0, "units": 250.0}
            for i in range(jobs.PRODUCT_PAGE_SIZE)]}}
        calls = {"n": 0}

        def vendor(tool: str, arguments: dict) -> str:
            if tool != "product_research":
                return fixture_vendor(tool, arguments)
            calls["n"] += 1
            return json.dumps(first if calls["n"] == 1 else page)

        with mock.patch.object(gateway.sellersprite, "call_tool", side_effect=vendor):
            result = jobs.run_job(self._job("product_pack"))
        self.assertEqual(result.status, "done")
        self.assertLess(result.calls, jobs.PRODUCT_PAGES,
                        "ran to the cap on pages worth nothing")
        snap = store.get_node_snapshot("US", BUFFETS, PERIOD)
        self.assertLess(snap["product_tail_pct"], jobs.PRODUCT_TAIL_PCT)

    def test_a_category_that_keeps_paying_is_followed_to_the_cap(self) -> None:
        """The other half of the same rule: depth is bounded by economics, and a
        category whose tail still sells gets the calls."""
        page = {"code": "OK", "data": {"total": 99_999, "items": [
            {"asin": f"C{i:04d}", "title": f"Listing {i}", "price": 300.0,
             "revenue": 50_000.0, "units": 160.0}
            for i in range(jobs.PRODUCT_PAGE_SIZE)]}}
        seen = {"n": 0}

        def vendor(tool: str, arguments: dict) -> str:
            if tool != "product_research":
                return fixture_vendor(tool, arguments)
            seen["n"] += 1
            payload = json.loads(json.dumps(page))
            for i, item in enumerate(payload["data"]["items"]):
                item["asin"] = f"C{seen['n']:02d}{i:03d}"
            return json.dumps(payload)

        gateway.DAILY_LIMITS[gateway.BUCKET_SWEEP] = 500
        with mock.patch.object(gateway.sellersprite, "call_tool", side_effect=vendor):
            result = jobs.run_job(self._job("product_pack"))
        self.assertEqual(result.calls, jobs.PRODUCT_PAGES)


class HistoryBackfillTests(SweepTestCase):
    """Almost every chart on the board is a trend, and every one of them was blank.

    ``growth_pct`` needs two stored months and the warehouse only ever collected
    the month it was run in, so the treemap's decline outlines, the department
    sparkline, the movers list and the quadrant's y axis were all waiting on a
    year of calendar time. ``market_research`` takes a ``month``; the history can
    simply be fetched.
    """

    def _job(self, kind: str, subject_id: str = BUFFETS, period: str = PERIOD) -> dict:
        store.enqueue_job(marketplace="US", job_kind=kind,
                          subject_kind=jobs.BY_KIND[kind].subject_kind,
                          subject_id=subject_id, period=period,
                          est_calls=jobs.BY_KIND[kind].est_calls)
        return next(j for j in store.due_jobs("US", limit=500) if j["job_kind"] == kind)

    def test_the_backfill_fills_every_missing_closed_month(self) -> None:
        with mock.patch.object(gateway.sellersprite, "call_tool",
                               side_effect=fixture_vendor):
            result = jobs.run_job(self._job("category_history"))
        self.assertEqual(result.status, "done")
        history = store.snapshot_history("US", BUFFETS)
        months = [row["period"] for row in history if row["total_revenue"] is not None]
        self.assertEqual(len(months), jobs.HISTORY_MONTHS)
        self.assertNotIn(PERIOD, months, "the backfill fills the past, not the present")

    def test_the_months_it_wrote_are_the_twelve_before_the_target(self) -> None:
        with mock.patch.object(gateway.sellersprite, "call_tool",
                               side_effect=fixture_vendor):
            jobs.run_job(self._job("category_history"))
        months = {row["period"] for row in store.snapshot_history("US", BUFFETS)}
        expected = {gateway.step_period(PERIOD, -offset)
                    for offset in range(1, jobs.HISTORY_MONTHS + 1)}
        self.assertEqual(months, expected)

    def test_a_month_already_stored_is_not_bought_twice(self) -> None:
        """Ongoing cost falls to nothing once the window is full.

        September's run looks back twelve months from September, which includes
        August — and August's own sweep already stored it through
        ``category_structure``. So the second run finds no gaps and spends nothing.
        """
        with mock.patch.object(gateway.sellersprite, "call_tool",
                               side_effect=fixture_vendor):
            jobs.run_job(self._job("category_history"))
            jobs.run_job(self._job("category_structure"))   # August, as the sweep does
            with mock.patch.object(gateway, "call") as vendor:
                again = jobs.run_job(self._job("category_history", period="202609"))
        vendor.assert_not_called()
        self.assertEqual(again.status, "done")
        self.assertEqual(again.calls, 0)

    def test_the_backfill_makes_growth_computable(self) -> None:
        """Which is the entire point: the trend charts had nothing to draw."""
        self.assertIsNone(scoring.growth_pct(store.snapshot_history("US", BUFFETS)))
        with mock.patch.object(gateway.sellersprite, "call_tool",
                               side_effect=fixture_vendor):
            jobs.run_job(self._job("category_history"))
        history = store.snapshot_history("US", BUFFETS)
        self.assertIsNotNone(scoring.growth_pct(history))
        self.assertNotEqual(scoring.growth_span(history), ("", ""))

    def test_running_out_of_budget_keeps_the_months_already_written(self) -> None:
        """Each month is committed before the next is asked for, so an interrupted
        backfill resumes with fewer gaps instead of starting over."""
        gateway.DAILY_LIMITS[gateway.BUCKET_SWEEP] = 4
        with mock.patch.object(gateway.sellersprite, "call_tool",
                               side_effect=fixture_vendor):
            result = jobs.run_job(self._job("category_history"))
        self.assertEqual(result.status, "budget")
        stored = [row for row in store.snapshot_history("US", BUFFETS)
                  if row["total_revenue"] is not None]
        self.assertEqual(len(stored), 4)
        # And the job is left exactly as it was, so tomorrow picks it up.
        queued = [j for j in store.due_jobs("US", limit=500)
                  if j["job_kind"] == "category_history"]
        self.assertEqual(len(queued), 1)
        self.assertEqual(int(queued[0]["attempts"] or 0), 0)

    def test_it_runs_last_so_the_current_month_never_waits_on_the_past(self) -> None:
        spec = jobs.BY_KIND["category_history"]
        self.assertEqual(spec.priority, max(s.priority for s in jobs.CATALOG))

    def test_it_is_not_part_of_the_completeness_pack(self) -> None:
        """A node whose history has not been fetched is not an incomplete month."""
        self.assertNotIn("category_history", jobs.NODE_PACK)


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

    def test_jobs_for_an_unclosed_month_are_parked_not_retried(self) -> None:
        """Retrying them is a day's budget spent proving the calendar."""
        store.enqueue_job(marketplace="US", job_kind="category_structure",
                          subject_kind="node", subject_id=BUFFETS, period="209901",
                          priority=30, est_calls=2)
        self.assertEqual(store.park_future_jobs("US", PERIOD), 1)
        self.assertEqual([j for j in store.due_jobs("US", limit=500)
                          if j["period"] == "209901"], [])

    def test_a_parked_month_wakes_when_it_closes(self) -> None:
        """Parking a month must not quietly retire it."""
        store.enqueue_job(marketplace="US", job_kind="category_structure",
                          subject_kind="node", subject_id=BUFFETS, period="209901",
                          priority=30, est_calls=2)
        store.park_future_jobs("US", PERIOD)
        jobs.plan_period("US", "209901")
        woken = [j for j in store.due_jobs("US", limit=500)
                 if j["period"] == "209901" and j["subject_id"] == BUFFETS
                 and j["job_kind"] == "category_structure"]
        self.assertEqual(len(woken), 1)
        self.assertEqual(woken[0]["attempts"], 0)

    def test_waking_does_not_reopen_a_finished_job(self) -> None:
        job = self._job("category_structure")
        store.finish_job(job["id"], status="done")
        jobs.plan_period("US", PERIOD)
        reopened = [j for j in store.due_jobs("US", limit=500)
                    if j["id"] == job["id"]]
        self.assertEqual(reopened, [])

    def test_the_board_renders_the_newest_usable_month_not_the_newest_one(self) -> None:
        """A stub current month must not outrank a complete previous month."""
        store.upsert_node_snapshot("US", BUFFETS, "202608", {
            "total_revenue": 6_907_337.97, "avg_price": 186.91})
        store.upsert_node_snapshot("US", BUFFETS, "202609", {"avg_price": 186.91})
        self.assertEqual(store.latest_period("US", usable_only=False), "202609")
        self.assertEqual(store.latest_period("US"), "202608")

    def test_a_warehouse_with_no_revenue_anywhere_still_renders_something(self) -> None:
        """Nothing to prefer is not a reason to show a blank page."""
        store.upsert_node_snapshot("US", BUFFETS, "202609", {"avg_price": 186.91})
        self.assertEqual(store.latest_period("US"), "202609")

    def test_a_board_with_no_revenue_drops_the_tile_rather_than_printing_zero(self) -> None:
        """Summing ``or 0.0`` over absent values states a measurement of $0.

        The tile is now dropped outright rather than shown as an em-dash: a KPI
        with nothing behind it is not a KPI, and a row of them buries the ones
        that did arrive.
        """
        from server.market import panels
        store.upsert_node_snapshot("US", BUFFETS, PERIOD, {"avg_price": 186.91})
        board = panels.build_overview("US", PERIOD, "zh")
        labels = [k["label"] for k in board["headline"]["kpis"]]
        self.assertFalse([label for label in labels if "销售额" in label])
        self.assertFalse([label for label in labels if "退货" in label])
        # No money figure may be printed as zero when none was collected. A
        # *count* of zero is a different thing — "no alerts fired" is an answer,
        # and dropping it would hide a real result.
        self.assertFalse([k for k in board["headline"]["kpis"]
                          if k["value"] in ("$0", "—")])
        self.assertIn("0", [k["value"] for k in board["headline"]["kpis"]])
        # The tiles that did arrive still show.
        self.assertTrue([label for label in labels if "子类目" in label])

    def test_what_was_dropped_is_still_reported_once(self) -> None:
        """Hiding empty sections must not hide that they are empty."""
        from server.market import panels
        store.upsert_node_snapshot("US", BUFFETS, PERIOD, {"avg_price": 186.91})
        board = panels.build_overview("US", PERIOD, "zh")
        missing = {f["key"] for f in board["coverage"]["families"] if not f["present"]}
        self.assertIn("distribution_price", missing)
        self.assertIn("product_research", missing)
        self.assertLess(board["coverage"]["present"], board["coverage"]["total"])

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
        gateway.DAILY_LIMITS[gateway.BUCKET_SWEEP] = 500
        with mock.patch.object(gateway.sellersprite, "call_tool", side_effect=fixture_vendor):
            summary = sweep.run_daily_sweep("US")
        self.assertEqual(summary["status"], "complete")
        snap = store.get_node_snapshot("US", BUFFETS, summary["period"])
        self.assertIsNotNone(snap)
        self.assertTrue(store.get_distribution("US", BUFFETS, summary["period"], "price"))
        self.assertTrue(store.get_concentration("US", BUFFETS, summary["period"], "brand"))
        self.assertTrue(store.top_products("US", BUFFETS, summary["period"]))
        # The wider roll-up needs the listing pool recorded alongside the ASINs.
        self.assertIsNotNone(snap.get("product_pool"))
        self.assertTrue(store.product_totals("US", summary["period"]))


if __name__ == "__main__":
    unittest.main()
