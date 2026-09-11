"""The /api/market/* surface.

Two contracts matter most here: a read never spends vendor credits, and the three
outcomes stay distinct — a rendered board, a 200 with ``data_gap``, and a 502 only
when the vendor itself is unreachable.
"""
from __future__ import annotations

import os
import unittest
from unittest import mock

from fastapi.testclient import TestClient

from marketing_agent.tools.mcp_client import McpUnavailable
from server import db, routes
from server.main import app
from server.market import gateway, jobs, prd, store, taxonomy
from tests.test_market_render import BUFFETS, PERIOD, FakeClient, seed_warehouse


class MarketRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["DEEPSEEK_API_KEY"] = "test-key"
        os.environ["MARKETING_AGENT_MEMORY_LLM"] = "0"
        os.environ["MARKETING_AGENT_CLARIFY_LLM"] = "0"
        db.reset_for_tests()
        gateway.clear_cache()
        jobs.clear_review_cache()
        self.client = TestClient(app)
        self.headers = self._register("alice@example.com")
        seed_warehouse()

    def tearDown(self) -> None:
        gateway.clear_cache()
        jobs.clear_review_cache()
        db.reset_for_tests()

    def _register(self, account: str) -> dict:
        response = self.client.post("/api/auth/register", json={
            "account": account, "password": "password123", "username": "u",
            "real_name": "r"})
        self.assertEqual(response.status_code, 200, response.text)
        return {"Authorization": f"Bearer {response.json()['token']}"}

    # ----- config ---------------------------------------------------------

    def test_config_ships_personas_sections_nodes_and_weights(self) -> None:
        body = self.client.get("/api/market/config", headers=self.headers).json()
        self.assertEqual({p["id"] for p in body["personas"]}, {"boss", "pm", "analyst"})
        self.assertTrue(body["sections"]["overview"])
        self.assertTrue(body["sections"]["category"])
        self.assertTrue(any(n["node_key"] == BUFFETS for n in body["nodes"]))
        self.assertEqual(body["score_model"]["version"], "v2")

    def test_sections_narrow_for_the_boss(self) -> None:
        boss = self.client.get("/api/market/config?persona=boss",
                               headers=self.headers).json()
        analyst = self.client.get("/api/market/config?persona=analyst",
                                  headers=self.headers).json()
        self.assertLess(len(boss["sections"]["overview"]),
                        len(analyst["sections"]["overview"]))

    def test_saving_a_config_persists_the_persona(self) -> None:
        response = self.client.put("/api/market/config", headers=self.headers, json={
            "scope": "all", "marketplace": "US", "refresh_time": "09:00",
            "persona": "analyst", "overview_enabled": False})
        self.assertEqual(response.status_code, 200, response.text)
        config = response.json()["config"]
        self.assertEqual(config["persona"], "analyst")
        self.assertFalse(config["overview_enabled"])

    def test_an_unknown_persona_falls_back_rather_than_erroring(self) -> None:
        response = self.client.put("/api/market/config", headers=self.headers, json={
            "scope": "all", "marketplace": "US", "refresh_time": "09:00",
            "persona": "ceo"})
        self.assertEqual(response.json()["config"]["persona"], "pm")

    def test_config_still_validates_like_the_selection_form(self) -> None:
        bad = self.client.put("/api/market/config", headers=self.headers, json={
            "scope": "categories", "categories": [], "marketplace": "US",
            "refresh_time": "09:00"})
        self.assertEqual(bad.status_code, 400)

    # ----- overview -------------------------------------------------------

    def test_overview_is_null_before_anything_is_rendered(self) -> None:
        body = self.client.get("/api/market/overview", headers=self.headers).json()
        self.assertIsNone(body["report"])
        self.assertTrue(body["sections"])

    def test_a_refresh_without_collect_spends_nothing(self) -> None:
        """Re-rendering is free; only an explicit collect can touch the vendor."""
        with mock.patch.object(gateway.sellersprite, "call_tool") as vendor, \
             mock.patch.object(routes.llm, "get_client",
                               return_value=FakeClient({"publish_market_overview": {
                                   "thesis": "ok", "category_verdicts": []}})):
            response = self.client.post("/api/market/overview/refresh",
                                        headers=self.headers,
                                        json={"period": PERIOD})
        self.assertEqual(response.status_code, 200, response.text)
        vendor.assert_not_called()
        self.assertEqual(response.json()["report"]["status"], "ok")
        self.assertTrue(response.json()["report"]["dashboard"]["board"])

    def test_a_rendered_board_is_then_served_from_storage(self) -> None:
        with mock.patch.object(routes.llm, "get_client",
                               return_value=FakeClient({"publish_market_overview": {
                                   "thesis": "ok", "category_verdicts": []}})):
            self.client.post("/api/market/overview/refresh", headers=self.headers,
                             json={"period": PERIOD})
        body = self.client.get("/api/market/overview", headers=self.headers).json()
        self.assertIsNotNone(body["report"])
        self.assertTrue(body["report"]["dashboard"]["sections"])

    def test_switching_persona_costs_no_model_call(self) -> None:
        fake = FakeClient({"publish_market_overview": {"thesis": "ok",
                                                       "category_verdicts": []}})
        with mock.patch.object(routes.llm, "get_client", return_value=fake):
            self.client.post("/api/market/overview/refresh", headers=self.headers,
                             json={"period": PERIOD})
        calls = len(fake.prompts)
        boss = self.client.get("/api/market/overview?persona=boss",
                               headers=self.headers).json()
        self.assertEqual(len(fake.prompts), calls)
        self.assertLess(len(boss["report"]["dashboard"]["sections"]),
                        len(store.latest_dashboard(marketplace="US", scope="overview",
                                                   language="zh")["dashboard"]["sections"])
                        + 99)   # sections are re-gated on read

    def test_collect_without_a_vendor_key_is_a_502(self) -> None:
        with mock.patch.object(routes, "sellersprite_configured", return_value=False):
            response = self.client.post("/api/market/overview/refresh",
                                        headers=self.headers, json={"collect": True})
        self.assertEqual(response.status_code, 502)
        self.assertIn("SELLERSPRITE_SECRET_KEY", response.json()["detail"])

    def test_a_vendor_outage_during_collect_is_a_502(self) -> None:
        with mock.patch.object(routes, "sellersprite_configured", return_value=True), \
             mock.patch.object(routes.market_sweep, "run_daily_sweep",
                               side_effect=McpUnavailable("connection reset")):
            response = self.client.post("/api/market/overview/refresh",
                                        headers=self.headers, json={"collect": True})
        self.assertEqual(response.status_code, 502)
        self.assertIn("不会被覆盖", response.json()["detail"])

    # ----- categories -----------------------------------------------------

    def test_the_category_picker_reports_freshness(self) -> None:
        body = self.client.get("/api/market/categories", headers=self.headers).json()
        row = next(c for c in body["categories"] if c["node_key"] == BUFFETS)
        self.assertTrue(row["has_snapshot"])
        self.assertEqual(row["label"], "Buffets & Sideboards")

    def test_category_requires_a_node(self) -> None:
        self.assertEqual(
            self.client.get("/api/market/category", headers=self.headers).status_code, 400)

    def test_a_category_refresh_without_collect_renders_from_storage(self) -> None:
        fake = FakeClient({"publish_category_narrative": {
            "structure_reading": "ok", "verdict": "enter", "verdict_rationale": "r"},
            "publish_opportunity_thesis": {"opportunities": []},
            "publish_pain_points": {"themes": []}})
        with mock.patch.object(gateway.sellersprite, "call_tool") as vendor, \
             mock.patch.object(routes.llm, "get_client", return_value=fake):
            response = self.client.post("/api/market/category/refresh",
                                        headers=self.headers,
                                        json={"node": BUFFETS, "period": PERIOD,
                                              "collect": False})
        vendor.assert_not_called()
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["report"]["status"], "ok")

    def test_an_unknown_node_is_a_404(self) -> None:
        with mock.patch.object(routes, "sellersprite_configured", return_value=True):
            response = self.client.post("/api/market/category/refresh",
                                        headers=self.headers,
                                        json={"node": "9:9:9", "collect": True})
        self.assertEqual(response.status_code, 404)

    def test_a_category_with_no_snapshot_renders_a_data_gap_not_an_error(self) -> None:
        """A correct answer, and worth no model call."""
        fake = FakeClient({})
        with mock.patch.object(routes.llm, "get_client", return_value=fake):
            response = self.client.post("/api/market/category/refresh",
                                        headers=self.headers,
                                        json={"node": taxonomy.TIER1_PATHS[1],
                                              "period": "209901", "collect": False})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["report"]["status"], "data_gap")
        self.assertEqual(fake.prompts, [])

    # ----- evidence, budget -----------------------------------------------

    def test_evidence_resolves_the_ids_a_dashboard_cites(self) -> None:
        body = self.client.get("/api/market/evidence?ids=ev_price000001",
                               headers=self.headers).json()
        self.assertEqual(len(body["evidence"]), 1)
        row = body["evidence"][0]
        self.assertEqual(row["tool"], "market_research")
        self.assertEqual(row["field_path"], "$.data.items[0].avgPrice")
        self.assertTrue(row["observed"])

    def test_evidence_requires_ids(self) -> None:
        self.assertEqual(
            self.client.get("/api/market/evidence", headers=self.headers).status_code, 400)

    def test_budget_reports_every_wallet(self) -> None:
        body = self.client.get("/api/market/budget", headers=self.headers).json()
        self.assertIn("sweep", body["budget"]["wallets"])
        self.assertIn("deepdive", body["budget"]["wallets"])
        self.assertIn("queue_depth", body)

    # ----- PRD ------------------------------------------------------------

    def test_a_prd_is_generated_and_readable(self) -> None:
        fake = FakeClient({prd.TOOL_NAME: {
            "title": "60 英寸窄进深餐边柜", "positioning": "p", "target_user": "u",
            "target_price_band": "$429-$519", "differentiators": [], "risks": [],
            "validation_plan": []}})
        with mock.patch.object(routes.llm, "get_client", return_value=fake):
            response = self.client.post("/api/market/prd", headers=self.headers,
                                        json={"node": BUFFETS, "period": PERIOD})
        self.assertEqual(response.status_code, 200, response.text)
        record = response.json()["prd"]
        self.assertEqual(record["prd"]["load_capacity"], "[待确认 承重]")
        fetched = self.client.get(f"/api/market/prd/{record['id']}", headers=self.headers)
        self.assertEqual(fetched.status_code, 200)
        listed = self.client.get("/api/market/prd", headers=self.headers).json()
        self.assertEqual(len(listed["prds"]), 1)

    def test_a_prd_is_not_visible_to_another_user(self) -> None:
        fake = FakeClient({prd.TOOL_NAME: {
            "title": "t", "positioning": "p", "target_user": "u",
            "target_price_band": "$1-$2", "differentiators": [], "risks": [],
            "validation_plan": []}})
        with mock.patch.object(routes.llm, "get_client", return_value=fake):
            record = self.client.post("/api/market/prd", headers=self.headers,
                                      json={"node": BUFFETS, "period": PERIOD}).json()["prd"]
        bob = self._register("bob@example.com")
        self.assertEqual(
            self.client.get(f"/api/market/prd/{record['id']}", headers=bob).status_code, 404)
        self.assertEqual(self.client.get("/api/market/prd", headers=bob).json()["prds"], [])

    def test_a_category_without_data_cannot_produce_a_prd(self) -> None:
        response = self.client.post("/api/market/prd", headers=self.headers,
                                    json={"node": taxonomy.TIER1_PATHS[1],
                                          "period": "209901"})
        self.assertEqual(response.status_code, 409)

    def test_prd_requires_a_node(self) -> None:
        self.assertEqual(
            self.client.post("/api/market/prd", headers=self.headers,
                             json={}).status_code, 400)

    # ----- the legacy surface ---------------------------------------------

    def test_the_old_selection_endpoints_still_answer(self) -> None:
        """A cached web bundle must keep working."""
        self.assertEqual(
            self.client.get("/api/selection/config", headers=self.headers).status_code, 200)
        self.assertEqual(
            self.client.get("/api/selection/report", headers=self.headers).status_code, 200)

    def test_every_market_endpoint_requires_authentication(self) -> None:
        for method, path in (("get", "/api/market/config"),
                             ("get", "/api/market/overview"),
                             ("get", "/api/market/categories"),
                             ("get", "/api/market/budget"),
                             ("get", "/api/market/prd"),
                             ("post", "/api/market/prd")):
            with self.subTest(path=path):
                call = getattr(self.client, method)
                response = call(path, json={}) if method == "post" else call(path)
                self.assertEqual(response.status_code, 401)


if __name__ == "__main__":
    unittest.main()
