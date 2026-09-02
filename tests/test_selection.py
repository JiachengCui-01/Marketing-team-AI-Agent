"""Tests for the automated product-selection analysis.

Offline throughout: the vendor is faked at ``sellersprite.call_tool`` and the model
at ``llm.get_client``.
"""
from __future__ import annotations

import json
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from fastapi.testclient import TestClient

from marketing_agent.tools.mcp_client import McpToolError, McpUnavailable
from server import db, selection
from server.main import app


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


class VendorSweepTests(unittest.TestCase):
    def test_sweep_resolves_the_node_first_and_drives_everything_off_it(self) -> None:
        calls: list[tuple[str, dict]] = []

        def fake_call(tool, arguments=None):
            calls.append((tool, arguments or {}))
            if tool == "product_node":
                return _NODE_REPLY
            return json.dumps({"ok": True})

        with mock.patch.object(selection.sellersprite, "call_tool", side_effect=fake_call):
            observations, tools_used = selection.collect_vendor_data(
                ["sofas and sectionals"], "US"
            )

        # Node lookup must come first; the rest is keyed off its id.
        self.assertEqual(
            [c[0] for c in calls],
            ["product_node", "market_research", "product_research", "market_product_demand_trend"],
        )
        node = "1055398:1063306:1063318:3733551"
        for tool, args in calls[1:]:
            self.assertEqual(args["request"]["nodeIdPath"], node, tool)
        # No free-text keyword reaches the data tools — that is what returned
        # toilet paper for a furniture query.
        self.assertTrue(all("keyword" not in a["request"] for _, a in calls[1:]))
        # Child nodes are included so a parent node still yields sectionals.
        product_args = next(a for t, a in calls if t == "product_research")
        self.assertEqual(product_args["request"]["nodeIdPathEqual"], "false")
        self.assertEqual(set(tools_used), {c[0] for c in calls})
        self.assertTrue(any(o.get("node") for o in observations))

        # The browse tree is a resolution step, not evidence. Inlining its ~20k-char
        # reply crowded out the payloads that actually carry the numbers, so only the
        # picked node is recorded.
        node_obs = [o for o in observations if o["tool"] == "product_node"]
        self.assertEqual(len(node_obs), 1)
        self.assertEqual(node_obs[0]["purpose"], "resolved browse node")
        self.assertNotIn("Office Products", node_obs[0]["payload"])
        self.assertIn(node, node_obs[0]["payload"])

    def test_the_prompt_carries_the_resolved_node_not_the_whole_tree(self) -> None:
        def fake_call(tool, arguments=None):
            return _NODE_REPLY if tool == "product_node" else json.dumps({"ok": True})

        with mock.patch.object(selection.sellersprite, "call_tool", side_effect=fake_call):
            observations, _ = selection.collect_vendor_data(["sofas and sectionals"], "US")
        content = selection._user_content(observations, ["sofas and sectionals"], "US", "zh")
        self.assertIn("Sofas & Couches", content)
        self.assertNotIn("Chairs & Sofas", content)  # the office-furniture row

    def test_an_unresolved_node_skips_the_data_calls_and_reports_a_gap(self) -> None:
        def fake_call(tool, arguments=None):
            if tool == "product_node":
                return json.dumps({"data": [
                    {"nodeIdPath": "x", "nodeLabelPath": "Health & Household:Toilet Paper",
                     "products": 5000},
                ]})
            return json.dumps({"ok": True})

        with mock.patch.object(selection.sellersprite, "call_tool", side_effect=fake_call) as call:
            observations, tools_used = selection.collect_vendor_data(["desks"], "US")

        # Better a stated gap than an analysis of the wrong category.
        self.assertEqual([c.args[0] for c in call.call_args_list], ["product_node"])
        self.assertEqual(tools_used, ["product_node"])
        self.assertTrue(any(o["status"] == "unresolved" for o in observations))

    def test_a_rejected_tool_does_not_sink_the_run(self) -> None:
        def fake_call(tool, arguments=None):
            if tool == "product_node":
                return _NODE_REPLY
            if tool == "market_research":
                raise McpToolError("marketplace is required")
            return json.dumps({"ok": True})

        with mock.patch.object(selection.sellersprite, "call_tool", side_effect=fake_call):
            observations, tools_used = selection.collect_vendor_data(["sofas"], "US")

        self.assertNotIn("market_research", tools_used)
        self.assertIn("product_research", tools_used)
        self.assertEqual(
            [o["tool"] for o in observations if o["status"] == "rejected"], ["market_research"]
        )

    def test_an_outage_propagates_rather_than_producing_a_thin_report(self) -> None:
        with mock.patch.object(
            selection.sellersprite, "call_tool", side_effect=McpUnavailable("gateway down")
        ):
            with self.assertRaises(McpUnavailable):
                selection.collect_vendor_data(["sofas"], "US")

    def test_the_call_budget_is_enforced_across_categories(self) -> None:
        with mock.patch.object(
            selection.sellersprite, "call_tool", return_value=_NODE_REPLY
        ) as call:
            selection.collect_vendor_data(
                [f"sofas {i}" for i in range(selection.MAX_CATEGORIES)], "US"
            )
        self.assertLessEqual(call.call_count, selection.MAX_VENDOR_CALLS)


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

    def test_generation_requires_the_vendor_and_never_falls_back(self) -> None:
        # A product recommendation not grounded in marketplace data would be a guess
        # dressed as analysis, so this feature has no web-search fallback.
        with mock.patch.object(selection.sellersprite, "is_configured", return_value=False):
            with self.assertRaises(selection.SelectionGenerationError) as ctx:
                selection.generate_report(self.config)
        self.assertIn("SELLERSPRITE_SECRET_KEY", str(ctx.exception))

    def test_a_vendor_that_answers_nothing_fails_loudly(self) -> None:
        with mock.patch.object(selection.sellersprite, "is_configured", return_value=True), \
                mock.patch.object(selection.sellersprite, "call_tool", return_value="  "), \
                mock.patch.object(selection.llm, "get_client", return_value=mock.Mock()):
            with self.assertRaises(selection.SelectionGenerationError) as ctx:
                selection.generate_report(self.config)
        self.assertIn("没有返回任何可用数据", str(ctx.exception))

    def test_successful_run_persists_the_dashboard_and_its_provenance(self) -> None:
        dashboard = {
            "kpis": [{"label": "类目均价", "value": "$899", "estimated": False}],
            "recommendations": [
                {"title": "实木餐桌", "category": "dining", "score": 78, "reason": "需求稳"}
            ],
            "trends": [
                {"category": "dining", "label": "月销量", "points": [
                    {"period": "202607", "value": 10}, {"period": "202608", "value": 14}
                ], "change_pct": 40.0}
            ],
            "market": [{"category": "dining", "verdict": "值得进入"}],
            "notes": ["desks 无数据"],
            "summary": "## 结论\n优先做实木餐桌。",
        }
        client = mock.Mock()
        client.messages.create.return_value = _tool_use_response(
            selection._TOOL_NAME, dashboard
        )
        with mock.patch.object(selection.sellersprite, "is_configured", return_value=True), \
                mock.patch.object(selection.sellersprite, "call_tool", return_value=_NODE_REPLY):
            record = selection.generate_report(self.config, client)

        self.assertEqual(record["dashboard"]["recommendations"][0]["score"], 78)
        self.assertIn("优先做实木餐桌", record["summary"])
        # Provenance is appended by the system, not written by the model.
        self.assertIn("## 数据来源", record["summary"])
        self.assertIn("卖家精灵", record["summary"])
        self.assertTrue(record["vendor_tools"])
        # The scheduler must see the run so it does not immediately re-fire.
        self.assertIsNotNone(db.get_selection_config(self.user["id"])["last_run_at"])

    def test_a_model_that_skips_the_tool_call_is_an_error_not_an_empty_report(self) -> None:
        client = mock.Mock()
        client.messages.create.return_value = mock.Mock(content=[mock.Mock(type="text")])
        with mock.patch.object(selection.sellersprite, "is_configured", return_value=True), \
                mock.patch.object(selection.sellersprite, "call_tool", return_value=_NODE_REPLY):
            with self.assertRaises(selection.SelectionGenerationError):
                selection.generate_report(self.config, client)


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


class ModelOutageTests(unittest.TestCase):
    """A 503 from the model must not discard the metered vendor sweep."""

    def setUp(self) -> None:
        db.reset_for_tests()
        selection.clear_sweep_cache()
        self.user = db.create_user(
            account="outage@example.com", password_hash="hash", username="O",
            real_name="Test User", id_card="11010519491231002X",
        )
        self.config = db.upsert_selection_config(
            self.user["id"], scope="all", refresh_time="09:00", timezone="UTC", language="zh"
        )

    def tearDown(self) -> None:
        selection.clear_sweep_cache()
        db.reset_for_tests()

    @staticmethod
    def _overloaded(status=503):
        exc = RuntimeError("503 Server Overloaded")
        exc.status_code = status
        return exc

    def test_transient_status_is_retried(self) -> None:
        client = mock.Mock()
        client.messages.create.side_effect = [
            self._overloaded(), self._overloaded(),
            _tool_use_response(selection._TOOL_NAME,
                               {"kpis": [], "recommendations": [], "summary": "ok"}),
        ]
        with mock.patch.object(selection.sellersprite, "is_configured", return_value=True),                 mock.patch.object(selection.sellersprite, "call_tool", return_value=_NODE_REPLY),                 mock.patch.object(selection.time, "sleep"):
            record = selection.generate_report(self.config, client)
        self.assertEqual(client.messages.create.call_count, 3)
        self.assertIn("ok", record["summary"])

    def test_a_non_transient_error_is_not_retried(self) -> None:
        exc = RuntimeError("401 bad key")
        exc.status_code = 401
        client = mock.Mock()
        client.messages.create.side_effect = exc
        with mock.patch.object(selection.sellersprite, "is_configured", return_value=True),                 mock.patch.object(selection.sellersprite, "call_tool", return_value=_NODE_REPLY):
            with self.assertRaises(selection.SelectionGenerationError):
                selection.generate_report(self.config, client)
        self.assertEqual(client.messages.create.call_count, 1)

    def test_persistent_overload_names_the_model_not_the_vendor(self) -> None:
        client = mock.Mock()
        client.messages.create.side_effect = self._overloaded()
        with mock.patch.object(selection.sellersprite, "is_configured", return_value=True),                 mock.patch.object(selection.sellersprite, "call_tool", return_value=_NODE_REPLY),                 mock.patch.object(selection.time, "sleep"):
            with self.assertRaises(selection.SelectionGenerationError) as ctx:
                selection.generate_report(self.config, client)
        message = str(ctx.exception)
        # "503" alone reads as if the data vendor were down.
        self.assertIn("DeepSeek", message)
        self.assertIn("缓存", message)

    def test_a_retry_after_an_outage_reuses_the_sweep_instead_of_paying_again(self) -> None:
        client = mock.Mock()
        client.messages.create.side_effect = self._overloaded()
        with mock.patch.object(selection.sellersprite, "is_configured", return_value=True),                 mock.patch.object(
                    selection.sellersprite, "call_tool", return_value=_NODE_REPLY
                ) as call,                 mock.patch.object(selection.time, "sleep"):
            with self.assertRaises(selection.SelectionGenerationError):
                selection.generate_report(self.config, client)
            first_calls = call.call_count
            self.assertGreater(first_calls, 0)

            # Second attempt: the model recovers, and the vendor is not touched again.
            client.messages.create.side_effect = None
            client.messages.create.return_value = _tool_use_response(
                selection._TOOL_NAME, {"kpis": [], "recommendations": [], "summary": "ok"}
            )
            record = selection.generate_report(self.config, client)

        self.assertEqual(call.call_count, first_calls, "vendor was charged twice")
        self.assertIn("ok", record["summary"])

    def test_an_expired_cache_re_runs_the_sweep(self) -> None:
        client = mock.Mock()
        client.messages.create.return_value = _tool_use_response(
            selection._TOOL_NAME, {"kpis": [], "recommendations": [], "summary": "ok"}
        )
        with mock.patch.object(selection.sellersprite, "is_configured", return_value=True),                 mock.patch.object(
                    selection.sellersprite, "call_tool", return_value=_NODE_REPLY
                ) as call:
            selection.generate_report(self.config, client)
            first = call.call_count
            with mock.patch.object(selection, "SWEEP_CACHE_TTL_SECONDS", -1):
                selection.generate_report(self.config, client)
        self.assertGreater(call.call_count, first)


if __name__ == "__main__":
    unittest.main()
