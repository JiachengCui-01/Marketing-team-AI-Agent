"""Rendering the two dashboards from stored data.

The invariant this file exists to protect: **rendering makes zero vendor calls**.
Everything the model sees is an evidence sheet built from SQLite, so a model outage
costs nothing and a hallucinated citation cannot survive to the screen.
"""
from __future__ import annotations

import json
import os
import pathlib
import unittest
from unittest import mock

from server import db
from server.market import gateway, jobs, render, store, sweep, taxonomy

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "sellersprite"
BUFFETS = "1055398:1063306:3733781:3733831"
PERIOD = "202608"


def tool_use(name: str, payload: dict):
    """A forced tool_use response shaped like ``llm_client`` returns."""
    block = mock.Mock(type="tool_use", input=payload)
    block.name = name
    return mock.Mock(content=[block])


class FakeClient:
    """Answers each publish tool from a canned payload, recording what it saw."""

    def __init__(self, payloads: dict[str, dict]) -> None:
        self.payloads = payloads
        self.prompts: list[str] = []
        self.messages = mock.Mock()
        self.messages.create = self._create

    def _create(self, **kwargs):
        name = kwargs["tools"][0]["name"]
        self.prompts.append(kwargs["messages"][0]["content"])
        return tool_use(name, self.payloads.get(name, {}))


def seed_warehouse(*, with_products: bool = True, with_keywords: bool = True) -> None:
    """A believable month for one node, written straight to the warehouse."""
    taxonomy.ensure_nodes()
    store.upsert_node_snapshot("US", BUFFETS, PERIOD, {
        "total_revenue": 6_907_337.97, "total_units": 40_000.0, "avg_price": 186.91,
        "avg_rating": 4.3, "avg_ratings": 800.0, "hl_avg_ratings": 788.0,
        "top5_brand_crn": 0.3929, "new_count_l12": 45.0,
        "new_avg_revenue_l12": 17_000.0, "new_ratio_l12": 0.45,
        "return_ratio": 0.015674, "return_ratio_avg": 0.028763,
    }, completeness=1.0, missing=[])
    store.upsert_node_snapshot("US", BUFFETS, "202607", {"total_revenue": 5_800_000.0})
    store.replace_distribution("US", BUFFETS, PERIOD, "price", [
        {"bucket_key": "50-100", "products": 20, "units": 9130, "revenue": 777_972.0,
         "units_ratio": 0.2281},
        {"bucket_key": "100-150", "products": 25, "units": 9533, "revenue": 1_202_347.0,
         "units_ratio": 0.2381},
    ])
    store.replace_concentration("US", BUFFETS, PERIOD, "brand", [
        {"entity": "VASAGLE", "rank": 1, "revenue_ratio": 0.0726, "units_ratio": 0.1213},
    ])
    if with_products:
        store.upsert_products([{"marketplace": "US", "asin": "B01", "title": "Oak sideboard",
                                "brand": "A"},
                               {"marketplace": "US", "asin": "B02", "title": "Walnut buffet",
                                "brand": "B"}])
        store.upsert_product_metrics([
            {"marketplace": "US", "asin": "B01", "period": PERIOD, "node_id_path": BUFFETS,
             "price": 429.0, "units": 1840.0, "revenue": 789_000.0, "bsr": 2140,
             "rating": 4.1, "ratings": 6310.0, "source_tool": "product_research"},
            {"marketplace": "US", "asin": "B02", "period": PERIOD, "node_id_path": BUFFETS,
             "price": 519.0, "units": 400.0, "revenue": 180_000.0, "bsr": 9000,
             "rating": 4.4, "ratings": 190.0, "source_tool": "product_research"},
        ])
    if with_keywords:
        store.upsert_keyword_metrics([{
            "marketplace": "US", "keyword": "sideboard buffet cabinet", "period": PERIOD,
            "node_id_path": BUFFETS, "searches": 17134.0, "supply_demand_ratio": 22.9,
            "source_tool": "keyword_research"}])
    store.record_evidence([
        {"id": "ev_price000001", "marketplace": "US", "tool": "market_research",
         "field_path": "$.data.items[0].avgPrice", "subject_kind": "node",
         "subject_id": BUFFETS, "metric": "avg_price", "period": PERIOD,
         "value_num": 186.91, "unit": "USD", "observed": True},
        {"id": "ev_rev00000001", "marketplace": "US", "tool": "market_research",
         "field_path": "$.data.items[0].totalRevenue", "subject_kind": "node",
         "subject_id": BUFFETS, "metric": "total_revenue", "period": PERIOD,
         "value_num": 6_907_337.97, "unit": "USD", "observed": False},
    ])


class RenderTestCase(unittest.TestCase):
    def setUp(self) -> None:
        db.reset_for_tests()
        gateway.clear_cache()
        jobs.clear_review_cache()
        seed_warehouse()

    def tearDown(self) -> None:
        gateway.clear_cache()
        jobs.clear_review_cache()
        db.reset_for_tests()


class OverviewTests(RenderTestCase):
    OVERVIEW = {
        "thesis": "餐边柜是本期最值得做的方向 [ev_price000001](evidence:ev_price000001)。",
        "category_verdicts": [
            {"node_key": BUFFETS, "verdict": "enter", "rationale": "集中度低、退货优于同级",
             "evidence_ids": ["ev_price000001"]},
            {"node_key": "9:9:9:9", "verdict": "enter", "rationale": "invented",
             "evidence_ids": ["ev_price000001"]},
        ],
        "notes": [],
    }

    def test_rendering_makes_no_vendor_calls(self) -> None:
        """The structural fix: ingest spends credits, render does not."""
        client = FakeClient({"publish_market_overview": self.OVERVIEW})
        with mock.patch.object(gateway.sellersprite, "call_tool") as vendor:
            record = render.render_overview(client=client, period=PERIOD)
        vendor.assert_not_called()
        self.assertEqual(record["status"], "ok")

    def test_the_board_is_scored_and_ranked_server_side(self) -> None:
        client = FakeClient({"publish_market_overview": self.OVERVIEW})
        record = render.render_overview(client=client, period=PERIOD)
        board = record["dashboard"]["board"]
        self.assertTrue(board)
        row = next(r for r in board if r["node_key"] == BUFFETS)
        self.assertGreater(row["category_score"], 0)
        self.assertIn("return_risk", row["score_breakdown"])
        self.assertEqual(board, sorted(board, key=lambda r: r["category_score"],
                                       reverse=True))

    def test_a_verdict_for_an_invented_node_is_dropped(self) -> None:
        client = FakeClient({"publish_market_overview": self.OVERVIEW})
        record = render.render_overview(client=client, period=PERIOD)
        self.assertIn(BUFFETS, record["dashboard"]["verdicts"])
        self.assertNotIn("9:9:9:9", record["dashboard"]["verdicts"])

    def test_the_model_is_shown_an_evidence_sheet_not_a_payload(self) -> None:
        client = FakeClient({"publish_market_overview": self.OVERVIEW})
        render.render_overview(client=client, period=PERIOD)
        prompt = client.prompts[0]
        self.assertIn("ev_price000001", prompt)
        self.assertNotIn("nodeLabelPathLocale", prompt)   # no raw vendor payload
        self.assertIn("ESTIMATE", prompt.replace("估算", "ESTIMATE"))

    def test_the_weights_ship_with_the_dashboard(self) -> None:
        client = FakeClient({"publish_market_overview": self.OVERVIEW})
        record = render.render_overview(client=client, period=PERIOD)
        self.assertEqual(record["dashboard"]["score_model"]["version"], "v2")

    def test_sections_follow_the_persona(self) -> None:
        client = FakeClient({"publish_market_overview": self.OVERVIEW})
        boss = render.render_overview(client=client, period=PERIOD, persona="boss",
                                      save=False)
        analyst = render.render_overview(client=client, period=PERIOD, persona="analyst",
                                         save=False)
        self.assertLess(len(boss["dashboard"]["sections"]),
                        len(analyst["dashboard"]["sections"]))

    def test_an_empty_period_is_a_data_gap_and_costs_no_model_call(self) -> None:
        """Spending a model call to write 'I have no data' is absurd."""
        db.reset_for_tests()
        taxonomy.ensure_nodes()
        client = FakeClient({})
        record = render.render_overview(client=client, period="209901")
        self.assertEqual(record["status"], "data_gap")
        self.assertEqual(client.prompts, [])
        self.assertTrue(record["summary"])

    def test_a_model_outage_still_produces_the_numbers(self) -> None:
        """The board is server-computed, so losing the narrative loses prose only."""
        broken = FakeClient({})
        broken.messages.create = mock.Mock(side_effect=RuntimeError("boom"))
        record = render.render_overview(client=broken, period=PERIOD)
        self.assertEqual(record["status"], "ok")
        self.assertTrue(record["dashboard"]["board"])
        self.assertEqual(record["dashboard"]["narrative_source"], "error")

    def test_no_client_degrades_to_numbers_only(self) -> None:
        record = render.render_overview(client=None, period=PERIOD)
        self.assertEqual(record["dashboard"]["narrative_source"], "unavailable")
        self.assertTrue(record["dashboard"]["board"])

    def test_the_dashboard_is_stored_and_readable(self) -> None:
        client = FakeClient({"publish_market_overview": self.OVERVIEW})
        render.render_overview(client=client, period=PERIOD, language="zh")
        stored = store.latest_dashboard(marketplace="US", scope="overview", language="zh")
        self.assertIsNotNone(stored)
        self.assertTrue(stored["evidence"])
        self.assertIn("market_research", stored["vendor_tools"])


class CategoryTests(RenderTestCase):
    NARRATIVE = {
        "structure_reading": "价格带重心在中段 [ev_price000001](evidence:ev_price000001)。",
        "keyword_intents": [{"keyword": "sideboard buffet cabinet", "intent": "attribute",
                             "note": "", "evidence_ids": ["ev_price000001"]}],
        "competitor_reading": [{"asin": "B01", "role": "volume_leader", "note": "",
                                "evidence_ids": ["ev_price000001"]}],
        "verdict": "enter",
        "verdict_rationale": "集中度低",
        "notes": [],
    }
    THESIS = {"opportunities": [{
        "anchor_asin": "B01", "title": "60 英寸窄进深餐边柜",
        "thesis": "切入中段价格带", "target_price_band": "$429-$519",
        "anchor_keywords": ["sideboard buffet cabinet"], "pain_themes": [],
        "differentiation_hypotheses": [
            {"claim": "四角护角", "backing": "pain_point",
             "evidence_ids": ["ev_price000001"]},
            {"claim": "实木贴皮", "backing": "pain_point",
             "evidence_ids": ["ev_invented00"]},
        ],
        "risks": [], "evidence_ids": ["ev_price000001"]}]}

    def _client(self) -> FakeClient:
        return FakeClient({"publish_category_narrative": self.NARRATIVE,
                           "publish_opportunity_thesis": self.THESIS,
                           "publish_pain_points": {"themes": []}})

    def test_a_category_renders_from_storage_only(self) -> None:
        client = self._client()
        with mock.patch.object(gateway.sellersprite, "call_tool") as vendor:
            record = render.render_category(node_id_path=BUFFETS, client=client,
                                            period=PERIOD)
        vendor.assert_not_called()
        self.assertEqual(record["status"], "ok")
        self.assertTrue(record["dashboard"]["competitors"])

    def test_opportunities_keep_the_server_score_and_gain_the_model_prose(self) -> None:
        record = render.render_category(node_id_path=BUFFETS, client=self._client(),
                                        period=PERIOD)
        top = record["dashboard"]["opportunities"][0]
        self.assertEqual(top["anchor_asin"], "B01")
        self.assertGreater(top["product_score"], 0)
        self.assertEqual(top["title"], "60 英寸窄进深餐边柜")
        self.assertIn("score_breakdown", top)

    def test_an_unsupported_hypothesis_is_dropped(self) -> None:
        """A differentiation claim citing an id that does not exist cannot survive."""
        record = render.render_category(node_id_path=BUFFETS, client=self._client(),
                                        period=PERIOD)
        claims = record["dashboard"]["opportunities"][0]["differentiation_hypotheses"]
        self.assertEqual([c["claim"] for c in claims], ["四角护角"])

    def test_a_missing_snapshot_is_a_data_gap(self) -> None:
        client = self._client()
        record = render.render_category(node_id_path="1:2:3", client=client, period=PERIOD)
        self.assertEqual(record["status"], "data_gap")
        self.assertEqual(client.prompts, [])

    def test_pain_themes_have_their_share_recomputed(self) -> None:
        """The model's own percentage is the one number it has an incentive to inflate."""
        jobs._REVIEW_CACHE[("US", "B01", PERIOD)] = [
            {"star": 1, "date": "2026-08-01", "title": "broken", "content": "corner crushed"}
            for _ in range(10)
        ]
        client = FakeClient({
            "publish_category_narrative": self.NARRATIVE,
            "publish_opportunity_thesis": self.THESIS,
            "publish_pain_points": {"themes": [
                {"theme": "运输磕碰", "category": "damage_in_transit", "sample_count": 4,
                 "severity": "blocking", "fixable_in_design": True,
                 "return_driving": True, "share_of_negative_pct": 99.0},
            ]}})
        render.render_category(node_id_path=BUFFETS, client=client, period=PERIOD)
        themes = store.review_themes("US", BUFFETS, PERIOD)
        self.assertEqual(len(themes), 1)
        self.assertAlmostEqual(themes[0]["share_of_negative"], 0.4)   # 4 of 10, not 99%
        self.assertEqual(themes[0]["sample_size"], 10)

    def test_a_theme_claiming_more_samples_than_exist_is_dropped(self) -> None:
        jobs._REVIEW_CACHE[("US", "B01", PERIOD)] = [
            {"star": 1, "date": "2026-08-01", "title": "x", "content": "y"}]
        client = FakeClient({
            "publish_category_narrative": self.NARRATIVE,
            "publish_opportunity_thesis": self.THESIS,
            "publish_pain_points": {"themes": [
                {"theme": "invented", "category": "other", "sample_count": 500,
                 "severity": "major", "fixable_in_design": True, "return_driving": False},
            ]}})
        render.render_category(node_id_path=BUFFETS, client=client, period=PERIOD)
        self.assertEqual(store.review_themes("US", BUFFETS, PERIOD), [])

    def test_no_reviews_is_reported_as_a_gap_not_silence(self) -> None:
        record = render.render_category(node_id_path=BUFFETS, client=self._client(),
                                        period=PERIOD)
        gaps = " ".join(record["dashboard"]["gaps"])
        self.assertIn("痛点", gaps)

    def test_uncollected_steps_are_named_in_the_gaps(self) -> None:
        record = render.render_category(node_id_path=BUFFETS, client=self._client(),
                                        period=PERIOD)
        gaps = " ".join(record["dashboard"]["gaps"])
        self.assertIn("category_structure", gaps)


class EndToEndTests(unittest.TestCase):
    """Collect with a faked vendor, then render — the whole chain, offline."""

    def setUp(self) -> None:
        db.reset_for_tests()
        gateway.clear_cache()
        jobs.clear_review_cache()
        self._env = {k: os.environ.get(k) for k in
                     ("MARKETING_AGENT_TEST_LIVE_VENDOR", "SELLERSPRITE_SECRET_KEY")}
        os.environ["MARKETING_AGENT_TEST_LIVE_VENDOR"] = "1"
        os.environ["SELLERSPRITE_SECRET_KEY"] = "test-key"
        self._limits = dict(gateway.DAILY_LIMITS)
        gateway.DAILY_LIMITS[gateway.BUCKET_SWEEP] = 200

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

    def test_sweep_then_render_produces_a_board_with_evidence(self) -> None:
        from tests.test_market_sweep import fixture_vendor

        with mock.patch.object(gateway.sellersprite, "call_tool", side_effect=fixture_vendor):
            summary = sweep.run_daily_sweep("US")
        client = FakeClient({"publish_market_overview": {
            "thesis": "ok", "category_verdicts": [], "notes": []}})
        record = render.render_overview(client=client, period=summary["period"])
        self.assertEqual(record["status"], "ok")
        self.assertTrue(record["dashboard"]["board"])
        self.assertTrue(record["evidence"])
        self.assertTrue(all(row["category_score"] >= 0
                            for row in record["dashboard"]["board"]))


if __name__ == "__main__":
    unittest.main()
