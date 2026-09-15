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
from server.market import (gateway, jobs, render, scoring, store, sweep,
                           taxonomy)

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
        # Physical columns: market_research returns them with every call and the
        # freight economics of this business are decided on them.
        "avg_weight": 96.4, "avg_volume": 38_500.0,
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
                                "brand": "A", "fulfillment": "FBA", "variations": 6,
                                "dimension": "60 x 18 x 32 inches", "weight": 128.6},
                               {"marketplace": "US", "asin": "B02", "title": "Walnut buffet",
                                "brand": "B", "fulfillment": "FBM", "variations": 3,
                                "dimension": "48 x 16 x 30 inches", "weight": 74.2}])
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

    def test_the_board_hands_the_model_the_alert_list(self) -> None:
        """Without the brief the model must invent risks or omit the section."""
        client = FakeClient({"publish_market_overview": self.OVERVIEW})
        render.render_overview(client=client, period=PERIOD)
        self.assertIn("RISK SIGNALS", client.prompts[0].replace("风险信号", "RISK SIGNALS"))

    def test_the_model_may_not_add_a_risk_of_its_own(self) -> None:
        client = FakeClient({"publish_market_overview": self.OVERVIEW})
        render.render_overview(client=client, period=PERIOD)
        instruction = "不得新增未列出的风险"
        self.assertIn(instruction, client.prompts[0])

    def test_the_weights_ship_with_the_dashboard(self) -> None:
        client = FakeClient({"publish_market_overview": self.OVERVIEW})
        record = render.render_overview(client=client, period=PERIOD)
        self.assertEqual(record["dashboard"]["score_model"]["version"], "v2")

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

    def test_the_deep_dive_hands_the_model_the_alert_list(self) -> None:
        """Each surface builds its own prompt, and one of them silently lost
        this line once already."""
        client = self._client()
        render.render_category(node_id_path=BUFFETS, client=client, period=PERIOD)
        self.assertIn("RISK SIGNALS", client.prompts[0].replace("风险信号", "RISK SIGNALS"))

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


class BoardReadTests(RenderTestCase):
    """Every row carries a written read, including the rows that are mostly gaps.

    A card with a score and nothing else is what the board looked like before, and
    it reads as a rendering failure rather than as a thin month.
    """

    # A real taxonomy leaf: build_overview iterates taxonomy.leaf_nodes, so a
    # made-up path produces no row at all and the assertion tests nothing.
    THIN = "1055398:1063306:1063308:3733251"  # Nightstands

    def read_of(self, payload: dict, node_key: str) -> dict[str, str]:
        row = next(r for r in payload["board"] if r["node_key"] == node_key)
        return {line["kind"]: line["text"] for line in row["read"]}

    def test_the_read_names_the_factors_behind_the_score(self) -> None:
        by_kind = self.read_of(render.build_overview("US", PERIOD, "zh"), BUFFETS)
        self.assertIn("分主要来自", by_kind["read"])
        self.assertIn("最大失分项", by_kind["read"])

    def test_the_shortfall_states_points_rather_than_claiming_a_zero(self) -> None:
        """A factor that earned 6 of 15 has not 'earned nothing'."""
        by_kind = self.read_of(render.build_overview("US", PERIOD, "zh"), BUFFETS)
        self.assertNotIn("没拿到分", by_kind["read"])
        self.assertRegex(by_kind["read"], r"\d+/\d+")

    def test_the_facts_line_is_the_product_brief_constraints(self) -> None:
        by_kind = self.read_of(render.build_overview("US", PERIOD, "zh"), BUFFETS)
        facts = by_kind["facts"]
        self.assertIn("96.4 lb", facts)
        self.assertIn("退货率", facts)
        self.assertIn("新品", facts)
        # The metric strip already names the price; a card that prints the same
        # number twice teaches people to skim past both.
        self.assertNotIn("类目均价", facts)

    def test_a_return_rate_well_under_peers_is_called_an_advantage(self) -> None:
        """For freight furniture this is worth more than most growth."""
        by_kind = self.read_of(render.build_overview("US", PERIOD, "zh"), BUFFETS)
        self.assertIn("结构性成本优势", by_kind["facts"])

    def test_a_thin_row_says_what_was_not_collected(self) -> None:
        store.upsert_node_snapshot("US", self.THIN, PERIOD, {"avg_price": 189.0},
                                   completeness=0.1, missing=["product_pack",
                                                              "keyword_demand"])
        by_kind = self.read_of(render.build_overview("US", PERIOD, "zh"), self.THIN)
        self.assertIn("本期未采集", by_kind["gap"])
        # Named for a reader, not as the queue's own job kinds.
        self.assertIn("竞品包", by_kind["gap"])
        self.assertNotIn("product_pack", by_kind["gap"])
        self.assertIn("不能和覆盖完整的类目直接比", by_kind["gap"])

    def test_a_row_with_nothing_to_say_says_nothing_rather_than_empty_labels(self) -> None:
        """No weight, no returns, no newcomer share — so no facts line at all."""
        store.upsert_node_snapshot("US", self.THIN, PERIOD, {"avg_price": 189.0},
                                   completeness=0.1, missing=[])
        by_kind = self.read_of(render.build_overview("US", PERIOD, "zh"), self.THIN)
        self.assertNotIn("facts", by_kind)
        self.assertIn("read", by_kind)

    def test_the_board_brief_hands_the_model_the_same_sentences(self) -> None:
        """Otherwise the thesis writes a second, differently-worded version."""
        payload = render.build_overview("US", PERIOD, "zh")
        brief = render._board_brief(payload["board"], "zh")
        self.assertIn("分主要来自", brief)
        self.assertIn("96.4 lb", brief)


class GrowthWindowTests(RenderTestCase):
    """A missing trend must not be drawn as a flat one.

    The treemap outlined declining categories in red and left everything else
    plain, so a department with one stored month rendered as "nothing is
    declining" — a claim nobody made and the data does not support.
    """

    SPARSE = "1055398:1063306:1063308:3733251"  # Nightstands

    def test_the_window_travels_with_the_growth_figure(self) -> None:
        payload = render.build_overview("US", PERIOD, "zh")
        row = next(r for r in payload["board"] if r["node_key"] == BUFFETS)
        self.assertEqual((row["growth_from"], row["growth_to"]), ("202607", PERIOD))

    def test_one_stored_month_yields_no_growth_and_no_window(self) -> None:
        store.upsert_node_snapshot("US", self.SPARSE, PERIOD,
                                   {"total_revenue": 2_000_000.0, "avg_price": 189.0},
                                   completeness=0.2, missing=[])
        payload = render.build_overview("US", PERIOD, "zh")
        row = next(r for r in payload["board"] if r["node_key"] == self.SPARSE)
        self.assertIsNone(row["growth_pct"])
        self.assertEqual((row["growth_from"], row["growth_to"]), ("", ""))

    def test_the_treemap_carries_the_same_distinction(self) -> None:
        """The chart has to be able to tell 'not declining' from 'cannot tell'."""
        store.upsert_node_snapshot("US", self.SPARSE, PERIOD,
                                   {"total_revenue": 2_000_000.0, "avg_price": 189.0},
                                   completeness=0.2, missing=[])
        payload = render.build_overview("US", PERIOD, "zh")
        by_key = {t["node_key"]: t for t in payload["treemap"]}
        self.assertIsNone(by_key[self.SPARSE]["growth_pct"])
        self.assertEqual(by_key[self.SPARSE]["growth_from"], "")
        self.assertIsNotNone(by_key[BUFFETS]["growth_pct"])
        self.assertEqual(by_key[BUFFETS]["growth_from"], "202607")

    def test_a_month_with_no_revenue_is_not_counted_as_an_endpoint(self) -> None:
        """A month the sweep never reached is not a month the category sold zero."""
        self.assertEqual(scoring.growth_span([
            {"period": "202605", "total_revenue": None},
            {"period": "202606", "total_revenue": 0.0},
            {"period": "202607", "total_revenue": 5_800_000.0},
            {"period": "202608", "total_revenue": 6_907_337.97},
        ]), ("202607", "202608"))

    def test_a_single_usable_month_reports_no_window(self) -> None:
        self.assertEqual(scoring.growth_span(
            [{"period": "202608", "total_revenue": 6_907_337.97}]), ("", ""))


class DirectionTests(RenderTestCase):
    """跟进 / 规避 — the two lists the board exists to produce."""

    def test_a_growing_low_return_category_lands_in_follow(self) -> None:
        payload = render.build_overview("US", PERIOD, "zh")
        entry = next(i for i in payload["follow"]
                     if i["kind"] == "category" and i["key"] == BUFFETS)
        self.assertIn("销售额 +", entry["why"])
        self.assertIn("退货率只有同级", entry["why"])

    def test_a_shrinking_entrenched_category_lands_in_avoid(self) -> None:
        crowded = "1055398:1063306:1063318:3733551"  # Sofas & Couches
        store.upsert_node_snapshot("US", crowded, "202607", {"total_revenue": 9_000_000.0})
        store.upsert_node_snapshot("US", crowded, PERIOD, {
            "total_revenue": 6_000_000.0, "avg_price": 740.0,
            "top5_brand_crn": 0.61, "hl_avg_ratings": 42_000.0,
            "return_ratio": 0.041, "return_ratio_avg": 0.0288,
        }, completeness=1.0, missing=[])
        payload = render.build_overview("US", PERIOD, "zh")
        entry = next(i for i in payload["avoid"]
                     if i["kind"] == "category" and i["key"] == crowded)
        self.assertIn("销售额 -", entry["why"])
        self.assertIn("Top5 品牌占 61%", entry["why"])
        self.assertIn("退货率是同级", entry["why"])

    def test_a_category_that_is_merely_flat_appears_on_neither_list(self) -> None:
        """A list that includes everything is a list nobody reads."""
        flat = "1055398:1063306:3733781:3733811"  # Tables
        store.upsert_node_snapshot("US", flat, "202607", {"total_revenue": 4_000_000.0})
        store.upsert_node_snapshot("US", flat, PERIOD, {
            "total_revenue": 4_080_000.0, "avg_price": 318.0, "top5_brand_crn": 0.30,
            "return_ratio": 0.028, "return_ratio_avg": 0.0288, "hl_avg_ratings": 900.0,
        }, completeness=1.0, missing=[])
        payload = render.build_overview("US", PERIOD, "zh")
        keys = {i["key"] for i in payload["follow"]} | {i["key"] for i in payload["avoid"]}
        self.assertNotIn(flat, keys)

    def test_rising_elements_reach_the_follow_list_with_their_phrases(self) -> None:
        store.upsert_keyword_metrics([
            {"marketplace": "US", "keyword": "fluted sideboard cabinet", "period": PERIOD,
             "node_id_path": BUFFETS, "searches": 11_000.0, "searches_growth": 0.42,
             "source_tool": "keyword_research"},
            {"marketplace": "US", "keyword": "fluted door console", "period": PERIOD,
             "node_id_path": BUFFETS, "searches": 6_000.0, "searches_growth": 0.31,
             "source_tool": "keyword_research"},
        ])
        payload = render.build_overview("US", PERIOD, "zh")
        entry = next(i for i in payload["follow"] if i["key"] == "fluted")
        self.assertEqual(entry["kind"], "element")
        self.assertIn("fluted sideboard cabinet", entry["keywords"])
        self.assertIn("2 个词", entry["why"])

    def test_the_direction_brief_is_omitted_rather_than_left_empty(self) -> None:
        payload = {"follow": [], "avoid": [], "elements": []}
        self.assertEqual(render._direction_brief(payload, "zh"), "")

    def test_the_model_may_not_invent_a_direction_of_its_own(self) -> None:
        """direction_reading is prose over a server-computed list, like every
        other narrative field here."""
        properties = render.TOOL_OVERVIEW["input_schema"]["properties"]
        self.assertIn("direction_reading", properties)
        self.assertIn("Do not add a category or element that is not in the lists",
                      properties["direction_reading"]["description"])


class ProductViewTests(RenderTestCase):
    """The report reads as a product development brief, not a traffic report.

    Three separate mechanisms have to hold for that to be true: the warehouse's
    physical columns have to reach the panel, the brief has to put them in front
    of the model ahead of the keyword list, and the directives the model writes
    back have to survive citation validation.
    """

    NARRATIVE = {
        "structure_reading": "中段价格带最厚 [ev_price000001](evidence:ev_price000001)。",
        "spec_reading": "货架均重 96.4 lb [ev_price000001](evidence:ev_price000001)。",
        "design_directives": [
            {"directive": "护角改注塑件", "driver": "packaging", "stage": "packaging",
             "priority": "must_fix", "note": "破损集中在四角。",
             "evidence_ids": ["ev_price000001"]},
            {"directive": "腿部预装", "driver": "assembly", "stage": "engineering",
             "priority": "differentiator", "note": "",
             "evidence_ids": ["ev_price000001"]},
            {"directive": "凭空想出来的改动", "driver": "to_validate", "stage": "concept",
             "priority": "nice_to_have", "note": "", "evidence_ids": ["ev_invented00"]},
        ],
        "entry_cost_reading": "头部广告占比未采集。",
        "verdict": "enter",
        "verdict_rationale": "退货率只有同级一半，货运家具最实在的优势",
        "notes": [],
    }

    def _client(self) -> FakeClient:
        return FakeClient({"publish_category_narrative": self.NARRATIVE,
                           "publish_opportunity_thesis": {"opportunities": []},
                           "publish_pain_points": {"themes": []}})

    # ---- the warehouse reaches the panel -----------------------------------

    def test_the_spec_envelope_is_built_from_stored_vendor_columns(self) -> None:
        """weight / dimension / variations were collected and then never shown."""
        payload = render.build_category("US", BUFFETS, PERIOD, "zh")
        spec = payload["spec"]
        labels = {tile["label"]: tile["value"] for tile in spec["tiles"]}
        self.assertIn("货架平均重量", labels)
        self.assertEqual(labels["货架平均重量"], "96.4 lb")
        self.assertEqual(labels["头部变体数中位"], "4.5")
        by_asin = {row["asin"]: row for row in spec["rows"]}
        self.assertEqual(by_asin["B01"]["dimension"], "60 x 18 x 32 inches")
        self.assertEqual(by_asin["B01"]["weight"], 128.6)

    def test_the_kpi_row_leads_with_the_product_constraints(self) -> None:
        """Weight used to live in a 'supply and logistics' section below the fold."""
        payload = render.build_category("US", BUFFETS, PERIOD, "zh")
        labels = [tile["label"] for tile in payload["header"]["kpis"]]
        self.assertIn("平均重量 / 体积", labels)
        # Three product constraints — what it sells for, what it weighs, what a
        # return costs — ahead of the market-structure tiles.
        self.assertLess(labels.index("平均重量 / 体积"), labels.index("Top5 品牌集中度"))
        self.assertLess(labels.index("退货率 / 同级均值"), labels.index("类目均分"))
        self.assertEqual(labels[:4], ["类目月销售额", "均价", "平均重量 / 体积",
                                      "退货率 / 同级均值"])

    def test_the_department_board_ranks_categories_by_price_density(self) -> None:
        """Freight scales with weight and the price does not; nothing else showed it."""
        store.upsert_node_snapshot("US", "1055398:1063306:1063308:3733251", PERIOD, {
            "total_revenue": 2_000_000.0, "avg_price": 90.0, "avg_weight": 60.0,
        }, completeness=1.0, missing=[])
        payload = render.build_overview("US", PERIOD, "zh")
        rows = payload["physical"]
        self.assertGreaterEqual(len(rows), 2, "both seeded nodes must reach the board")
        densities = [r["price_per_lb"] for r in rows if r["price_per_lb"] is not None]
        self.assertEqual(densities, sorted(densities, reverse=True))
        buffets = next(r for r in rows if r["node_key"] == BUFFETS)
        self.assertAlmostEqual(buffets["price_per_lb"], round(186.91 / 96.4, 2))

    # ---- the brief puts the product problem first --------------------------

    def test_the_brief_leads_with_complaints_and_specs_not_keywords(self) -> None:
        """What leads the input is what leads the output."""
        store.replace_review_themes("US", BUFFETS, PERIOD, [{
            "theme": "四角破损", "theme_label": "四角破损", "category": "damage_in_transit",
            "severity": "major", "fixable_in_design": True, "return_driving": True,
            "mention_count": 14, "sample_size": 60, "share_of_negative": 0.2333,
            "summary": "", "quotes": [], "evidence_ids": [],
        }])
        payload = render.build_category("US", BUFFETS, PERIOD, "zh")
        brief = render._category_brief(payload, "zh")
        self.assertLess(brief.index("DESIGN-ACTIONABLE COMPLAINTS"),
                        brief.index("PHYSICAL ENVELOPE"))
        self.assertLess(brief.index("PHYSICAL ENVELOPE"),
                        brief.index("DEMAND VOCABULARY"))
        self.assertIn("fixable_in_design return_driving", brief)
        self.assertIn("60 x 18 x 32 inches", brief)

    def test_the_brief_survives_a_node_with_no_themes_or_specs(self) -> None:
        """A gap must drop its heading, not print an empty one."""
        payload = render.build_category("US", BUFFETS, PERIOD, "zh")
        payload["pain"] = []
        payload["spec"] = {"tiles": [], "rows": []}
        brief = render._category_brief(payload, "zh")
        self.assertIn("DEMAND VOCABULARY", brief)
        self.assertNotIn("PHYSICAL ENVELOPE", brief)

    # ---- the model's product output survives the round trip ----------------

    def test_design_directives_reach_the_dashboard(self) -> None:
        record = render.render_category(node_id_path=BUFFETS, client=self._client(),
                                        period=PERIOD)
        directives = record["dashboard"]["design_directives"]
        self.assertEqual([d["directive"] for d in directives],
                         ["护角改注塑件", "腿部预装"])
        self.assertEqual(directives[0]["stage"], "packaging")
        self.assertEqual(record["dashboard"]["spec_reading"][:4], "货架均重")

    def test_an_uncited_directive_is_dropped_like_every_other_claim(self) -> None:
        """A directive is an instruction to spend tooling money. It cites or it goes."""
        record = render.render_category(node_id_path=BUFFETS, client=self._client(),
                                        period=PERIOD)
        written = [d["directive"] for d in record["dashboard"]["design_directives"]]
        self.assertNotIn("凭空想出来的改动", written)

    def test_the_narrative_tool_no_longer_asks_for_a_traffic_reading(self) -> None:
        """It asked for one for months and no view ever rendered it."""
        properties = render.TOOL_CATEGORY["input_schema"]["properties"]
        self.assertNotIn("traffic_reading", properties)
        self.assertIn("design_directives", properties)
        self.assertIn("spec_reading", properties)
        self.assertIn("entry_cost_reading", properties)


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
