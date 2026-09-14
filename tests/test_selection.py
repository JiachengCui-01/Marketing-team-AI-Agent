"""Tests for the legacy product-selection surface.

Collection moved to ``server/market/`` — what is left here is the schedule, the
cancellation grace period, the category picker, and the projection of the market
board into the legacy response shape. Offline throughout; the point of most of
these is that no vendor call happens at all.
"""
from __future__ import annotations

import json
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from fastapi.testclient import TestClient

from server import db, selection
from server.main import app
from server.market import gateway, store as market_store

BUFFETS = "1055398:1063306:3733781:3733831"


def _tool_use_response(name: str, payload: dict):
    """A fake forced tool_use response shaped like ``llm_client`` returns.

    ``name`` cannot be passed to the Mock constructor — it is reserved for the mock's
    own repr — so it is assigned afterwards.
    """
    block = mock.Mock(type="tool_use", input=payload)
    block.name = name
    return mock.Mock(content=[block])


class CategoryResolutionTests(unittest.TestCase):
    def test_all_scope_uses_the_brands_own_product_line(self) -> None:
        # "Everything" must not mean all of Amazon: a recommendation outside what this
        # company can design and freight is noise.
        picked = selection.resolve_categories({"scope": "all", "categories": []})
        self.assertTrue(picked)
        self.assertTrue(set(picked).issubset(set(selection.ALL_CATEGORY_KEYWORDS)))
        self.assertLessEqual(len(picked), selection.MAX_CATEGORIES)

    def test_specific_scope_uses_and_bounds_the_user_list(self) -> None:
        picked = selection.resolve_categories(
            {"scope": "categories", "categories": [f"cat{i}" for i in range(9)]}
        )
        self.assertEqual(len(picked), selection.MAX_CATEGORIES)
        self.assertEqual(picked[0], "cat0")

    def test_specific_scope_with_an_empty_list_falls_back_to_the_product_line(self) -> None:
        picked = selection.resolve_categories({"scope": "categories", "categories": []})
        self.assertTrue(set(picked).issubset(set(selection.ALL_CATEGORY_KEYWORDS)))


# A trimmed real ``product_node`` reply: the vendor returns the right furniture node
# alongside an office-furniture node for the same keyword.
_NODE_REPLY = json.dumps({
    "code": "OK",
    "data": [
        {
            "nodeIdPath": "1064954:1069102:1069122",
            "nodeLabelPath": "Office Products:Office Furniture & Lighting:Chairs & Sofas",
            "products": 3330,
        },
        {
            "nodeIdPath": "1055398:1063306:1063318:3733551",
            "nodeLabelPath": "Home & Kitchen:Furniture:Living Room Furniture:Sofas & Couches",
            "products": 10941,
        },
    ],
})


class NodePickingTests(unittest.TestCase):
    def test_home_furniture_beats_office_furniture(self) -> None:
        # A "sofa" under Office Products is a task chair — different price band,
        # buyer, and freight profile than what this brand sells.
        path, label = selection.pick_node(_NODE_REPLY, "sofas and sectionals")
        self.assertEqual(path, "1055398:1063306:1063318:3733551")
        self.assertIn("Home & Kitchen", label)

    def test_listing_count_only_breaks_ties(self) -> None:
        # Both rows are in the home tree; the keyword match must decide, not size.
        reply = json.dumps({"data": [
            {"nodeIdPath": "a", "nodeLabelPath": "Home & Kitchen:Furniture:Mattresses",
             "products": 90000},
            {"nodeIdPath": "b", "nodeLabelPath": "Home & Kitchen:Furniture:Game & Recreation Room Furniture:Desks",
             "products": 800},
        ]})
        path, _ = selection.pick_node(reply, "desks")
        self.assertEqual(path, "b")

    def test_no_furniture_or_keyword_match_yields_none(self) -> None:
        reply = json.dumps({"data": [
            {"nodeIdPath": "x", "nodeLabelPath": "Health & Household:Toilet Paper", "products": 5000},
        ]})
        self.assertIsNone(selection.pick_node(reply, "sofas and sectionals"))

    def test_unparseable_or_empty_payload_yields_none(self) -> None:
        self.assertIsNone(selection.pick_node("not json", "desks"))
        self.assertIsNone(selection.pick_node(json.dumps({"data": []}), "desks"))


class ScheduleTests(unittest.TestCase):
    def _now(self, hour: int, minute: int = 0) -> datetime:
        return datetime(2026, 9, 2, hour, minute, tzinfo=timezone.utc)

    def test_not_due_before_the_configured_time(self) -> None:
        self.assertFalse(
            selection.is_due({"refresh_time": "09:00", "last_run_at": None}, self._now(8))
        )

    def test_due_on_the_first_run_after_the_time(self) -> None:
        self.assertTrue(
            selection.is_due({"refresh_time": "09:00", "last_run_at": None}, self._now(9, 30))
        )

    def test_not_due_twice_in_the_same_day(self) -> None:
        already = self._now(9, 5).timestamp()
        self.assertFalse(
            selection.is_due({"refresh_time": "09:00", "last_run_at": already}, self._now(18))
        )

    def test_due_again_the_next_day(self) -> None:
        yesterday = (self._now(9, 5) - timedelta(days=1)).timestamp()
        self.assertTrue(
            selection.is_due({"refresh_time": "09:00", "last_run_at": yesterday}, self._now(9, 1))
        )

    def test_a_malformed_time_never_fires(self) -> None:
        self.assertFalse(selection.is_due({"refresh_time": "nope"}, self._now(23)))


class GenerationTests(unittest.TestCase):
    """The legacy report is now a projection of the market board, not a sweep."""

    BOARD = {
        "headline": {"kpis": [{"label": "家具大盘月销售额", "value": "$7.92M",
                               "hint": "", "estimated": True}]},
        "board": [
            {"node_key": BUFFETS, "label": "Buffets & Sideboards",
             "node_label_path": "Furniture:Buffets & Sideboards",
             "category_score": 71, "score_breakdown": {"demand_scale": 8.0},
             "score_confidence": 0.9, "revenue_est": 7_920_000.0, "growth_pct": 4.0,
             "median_price": 214.0, "top5_brand_share_pct": 18.0,
             "new_revenue_share_pct": 38.4, "return_ratio_pct": 1.77,
             "return_ratio_avg_pct": 3.31, "return_risk": 0.0,
             "completeness": 1.0, "missing": []},
        ],
        "verdicts": {BUFFETS: {"verdict": "enter", "rationale": "集中度低、退货优于同级",
                               "evidence_ids": []}},
        "trend": [{"period": "202607", "value": 7_000_000.0},
                  {"period": "202608", "value": 7_920_000.0}],
        "thesis": "餐边柜是本期最值得做的方向。",
        "monitor_summary": "退货率只有同级的 0.54 倍。",
        "gaps": ["评论痛点未采集"],
    }

    def setUp(self) -> None:
        db.reset_for_tests()
        self.user = db.create_user(
            account="sel@example.com",
            password_hash="hash",
            username="Sel",
            real_name="Test User",
            id_card="11010519491231002X",
        )
        self.config = db.upsert_selection_config(
            self.user["id"], scope="all", refresh_time="09:00", timezone="UTC", language="zh"
        )

    def tearDown(self) -> None:
        db.reset_for_tests()

    def _store_board(self, language: str = "zh") -> dict:
        return market_store.save_dashboard(
            user_id=None, marketplace="US", scope="overview", node_id_path=None,
            period="202608", language=language, status="ok", dashboard=self.BOARD,
            summary=self.BOARD["thesis"], evidence=[],
            vendor_tools=["market_research", "product_research"],
            data_as_of=None, completeness=1.0)

    def test_a_report_costs_no_vendor_call_at_all(self) -> None:
        """The whole point of the rewrite: collection is global and already paid for."""
        self._store_board()
        with mock.patch.object(gateway.sellersprite, "call_tool") as vendor:
            record = selection.generate_report(self.config)
        vendor.assert_not_called()
        self.assertTrue(record["dashboard"]["recommendations"])

    def test_a_stored_board_is_reused_instead_of_re_rendered(self) -> None:
        """N users must cost one render, not N model calls."""
        self._store_board()
        client = mock.Mock()
        selection.generate_report(self.config, client)
        selection.generate_report(self.config, client)
        client.messages.create.assert_not_called()

    def test_an_empty_warehouse_fails_loudly_rather_than_guessing(self) -> None:
        with mock.patch.object(selection.llm, "get_client", return_value=None):
            with self.assertRaises(selection.SelectionGenerationError) as ctx:
                selection.generate_report(self.config)
        self.assertIn("DEEPSEEK_API_KEY", str(ctx.exception))

    def test_a_data_gap_board_is_an_error_not_an_empty_dashboard(self) -> None:
        market_store.save_dashboard(
            user_id=None, marketplace="US", scope="overview", node_id_path=None,
            period="202608", language="zh", status="data_gap",
            dashboard={"gaps": ["本期没有任何类目快照"]}, summary="没有可用数据。",
            evidence=[], vendor_tools=[], data_as_of=None, completeness=0.0)
        with self.assertRaises(selection.SelectionGenerationError) as ctx:
            selection.generate_report(self.config)
        self.assertIn("没有可用数据", str(ctx.exception))

    def test_the_projection_carries_the_boards_own_numbers(self) -> None:
        self._store_board()
        record = selection.generate_report(self.config)
        dashboard = record["dashboard"]
        row = dashboard["recommendations"][0]
        self.assertEqual(row["title"], "Buffets & Sideboards")
        self.assertEqual(row["score"], 71)
        self.assertEqual(row["reason"], "集中度低、退货优于同级")
        # 18% of revenue in the top five brands is a low-concentration market.
        self.assertEqual(row["competition"], "low")
        self.assertEqual(dashboard["market"][0]["brand_concentration"], "18.0%")
        self.assertEqual(dashboard["kpis"], self.BOARD["headline"]["kpis"])
        self.assertEqual(dashboard["notes"], ["评论痛点未采集"])

    def test_the_monitoring_summary_reaches_the_legacy_summary(self) -> None:
        self._store_board()
        record = selection.generate_report(self.config)
        self.assertIn("餐边柜是本期最值得做的方向", record["summary"])
        self.assertIn("退货率只有同级的 0.54 倍", record["summary"])

    def test_provenance_is_still_appended(self) -> None:
        self._store_board()
        record = selection.generate_report(self.config)
        self.assertIn("卖家精灵", record["summary"])
        self.assertEqual(record["vendor_tools"], ["market_research", "product_research"])

    def test_the_run_stamps_the_config_so_it_is_not_due_again_today(self) -> None:
        self._store_board()
        selection.generate_report(self.config)
        config = db.get_selection_config(self.user["id"])
        self.assertIsNotNone(config["last_run_at"])
        now = datetime.fromtimestamp(config["last_run_at"], tz=timezone.utc)
        self.assertFalse(selection.is_due(config, now))


class PurgeTests(unittest.TestCase):
    """Turning the task off has to take the user's market artifacts with it."""

    def setUp(self) -> None:
        db.reset_for_tests()
        self.user = db.create_user(
            account="purge@example.com", password_hash="hash", username="P",
            real_name="Test User", id_card="11010519491231002X")

    def tearDown(self) -> None:
        db.reset_for_tests()

    def test_purge_removes_the_users_dashboards_and_prds(self) -> None:
        db.upsert_selection_config(self.user["id"], scope="all", refresh_time="09:00")
        market_store.save_dashboard(
            user_id=self.user["id"], marketplace="US", scope="category",
            node_id_path=BUFFETS, period="202608", language="zh", status="ok",
            dashboard={"board": []}, summary="", evidence=[], vendor_tools=[],
            data_as_of=None, completeness=1.0)
        market_store.add_prd(
            user_id=self.user["id"], marketplace="US", node_id_path=BUFFETS,
            period="202608", language="zh", opportunity_id="op", title="T",
            prd={}, assumptions=[],
            evidence_ids=[], notes=[])

        selection.purge_user_data(self.user["id"])

        self.assertIsNone(db.get_selection_config(self.user["id"]))
        with db.connect() as conn:
            left = conn.execute(
                "SELECT COUNT(*) FROM market_dashboards WHERE user_id = ?",
                (self.user["id"],)).fetchone()[0]
        self.assertEqual(left, 0)
        self.assertEqual(market_store.list_prds(self.user["id"]), [])

    def test_the_global_warehouse_survives_a_purge(self) -> None:
        """It is nobody's personal data and re-collecting it costs real credits."""
        db.upsert_selection_config(self.user["id"], scope="all", refresh_time="09:00")
        market_store.upsert_node_snapshot("US", BUFFETS, "202608",
                                          {"total_revenue": 1.0})
        market_store.save_dashboard(
            user_id=None, marketplace="US", scope="overview", node_id_path=None,
            period="202608", language="zh", status="ok", dashboard={"board": []},
            summary="", evidence=[], vendor_tools=[], data_as_of=None, completeness=1.0)

        selection.purge_user_data(self.user["id"])

        self.assertIsNotNone(market_store.get_node_snapshot("US", BUFFETS, "202608"))
        self.assertIsNotNone(market_store.latest_dashboard(
            marketplace="US", scope="overview", language="zh"))


class SelectionRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        db.reset_for_tests()
        self.client = TestClient(app)
        response = self.client.post(
            "/api/auth/register",
            json={
                "account": "route@example.com",
                "password": "Passw0rd!",
                "username": "R",
                "real_name": "张三",
                "id_card": "11010519491231002X",
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.headers = {"Authorization": f"Bearer {response.json()['token']}"}

    def tearDown(self) -> None:
        db.reset_for_tests()

    def test_config_endpoint_offers_the_pickers_options(self) -> None:
        body = self.client.get("/api/selection/config", headers=self.headers).json()
        self.assertIsNone(body["config"])
        self.assertIn("US", body["marketplaces"])
        self.assertTrue(body["default_categories"])

    def test_scope_and_time_are_validated(self) -> None:
        bad_scope = self.client.put(
            "/api/selection/config", headers=self.headers, json={"scope": "everything"}
        )
        self.assertEqual(bad_scope.status_code, 400)

        empty_list = self.client.put(
            "/api/selection/config",
            headers=self.headers,
            json={"scope": "categories", "categories": [], "refresh_time": "09:00"},
        )
        self.assertEqual(empty_list.status_code, 400)

        bad_time = self.client.put(
            "/api/selection/config",
            headers=self.headers,
            json={"scope": "all", "refresh_time": "9am"},
        )
        self.assertEqual(bad_time.status_code, 400)

        bad_market = self.client.put(
            "/api/selection/config",
            headers=self.headers,
            json={"scope": "all", "refresh_time": "09:00", "marketplace": "ZZ"},
        )
        self.assertEqual(bad_market.status_code, 400)

    def test_legacy_delete_soft_cancels_without_erasing_reports(self) -> None:
        saved = self.client.put(
            "/api/selection/config",
            headers=self.headers,
            json={
                "scope": "categories",
                "categories": ["sofas", "desks"],
                "marketplace": "US",
                "refresh_time": "07:30",
                "timezone": "Asia/Shanghai",
                "language": "zh",
            },
        )
        self.assertEqual(saved.status_code, 200, saved.text)
        config = saved.json()["config"]
        self.assertEqual(config["categories"], ["sofas", "desks"])
        self.assertEqual(config["refresh_time"], "07:30")

        user = self.client.get("/api/auth/me", headers=self.headers).json()["user"]
        db.add_selection_report(
            user["id"], "US", "categories", ["sofas", "desks"],
            {}, "legacy retained report", [], 1.0,
        )

        deleted = self.client.delete("/api/selection/config", headers=self.headers)
        self.assertEqual(deleted.status_code, 200)
        after = self.client.get("/api/selection/config", headers=self.headers).json()
        self.assertFalse(after["config"]["enabled"])
        report = self.client.get("/api/selection/report", headers=self.headers).json()["report"]
        self.assertEqual(report["summary"], "legacy retained report")

    def test_cancel_keeps_report_and_saving_reactivates_task(self) -> None:
        saved = self.client.put(
            "/api/selection/config",
            headers=self.headers,
            json={
                "scope": "categories",
                "categories": ["sofas"],
                "marketplace": "US",
                "refresh_time": "09:00",
                "timezone": "UTC",
                "language": "zh",
            },
        ).json()["config"]
        user = self.client.get("/api/auth/me", headers=self.headers).json()["user"]
        db.add_selection_report(
            user["id"], "US", "categories", ["sofas"],
            {"kpis": [{"label": "Revenue", "value": "$1"}]},
            "retained report", ["market_research"], 1.0,
        )

        cancelled = self.client.post("/api/selection/cancel", headers=self.headers)
        self.assertEqual(cancelled.status_code, 200, cancelled.text)
        cancelled_config = cancelled.json()["config"]
        self.assertFalse(cancelled_config["enabled"])
        self.assertIsNotNone(cancelled_config["cancelled_at"])
        self.assertIn("revert_at", cancelled_config)

        report = self.client.get("/api/selection/report", headers=self.headers).json()["report"]
        self.assertEqual(report["summary"], "retained report")
        blocked = self.client.post("/api/selection/refresh", headers=self.headers, json={})
        self.assertEqual(blocked.status_code, 409)

        reactivated = self.client.put(
            "/api/selection/config",
            headers=self.headers,
            json={
                "scope": saved["scope"],
                "categories": saved["categories"],
                "marketplace": saved["marketplace"],
                "refresh_time": saved["refresh_time"],
                "timezone": saved["timezone"],
                "language": saved["language"],
            },
        ).json()["config"]
        self.assertTrue(reactivated["enabled"])
        self.assertIsNone(reactivated["cancelled_at"])

    def test_refresh_requires_a_configured_task(self) -> None:
        response = self.client.post("/api/selection/refresh", headers=self.headers, json={})
        self.assertEqual(response.status_code, 400)

    def test_a_generation_failure_surfaces_as_502_with_the_reason(self) -> None:
        self.client.put(
            "/api/selection/config",
            headers=self.headers,
            json={"scope": "all", "refresh_time": "09:00"},
        )
        with mock.patch.object(
            selection,
            "generate_report",
            side_effect=selection.SelectionGenerationError("卖家精灵接口暂时不可用"),
        ):
            response = self.client.post("/api/selection/refresh", headers=self.headers, json={})
        self.assertEqual(response.status_code, 502)
        self.assertIn("卖家精灵", response.json()["detail"])

    def test_approvals_endpoints_are_gone(self) -> None:
        for method, path in (
            ("get", "/api/approvals"),
            ("post", "/api/approvals"),
            ("get", "/api/approvals/x"),
        ):
            response = getattr(self.client, method)(path, headers=self.headers)
            self.assertEqual(response.status_code, 404, f"{method} {path}")
