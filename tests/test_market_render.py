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
from server.market import (elements, gateway, jobs, panels, render, scoring,
                           store, sweep, taxonomy)

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
        self.by_tool: dict[str, str] = {}
        self.messages = mock.Mock()
        self.messages.create = self._create

    def _create(self, **kwargs):
        name = kwargs["tools"][0]["name"]
        self.prompts.append(kwargs["messages"][0]["content"])
        self.by_tool[name] = kwargs["messages"][0]["content"]
        return tool_use(name, self.payloads.get(name, {}))

    def prompt_for(self, tool: str) -> str:
        """The prompt one tool saw. Indexing by position broke the moment the
        render made a second model call for something else."""
        return self.by_tool.get(tool, "")


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

    def test_the_card_can_tell_a_zero_from_an_unmeasured_factor(self) -> None:
        """The card lists every factor, so it has to say which zeros are
        readings. Both are 0 points and they are different sentences."""
        client = FakeClient({"publish_market_overview": self.OVERVIEW})
        record = render.render_overview(client=client, period=PERIOD)
        row = next(r for r in record["dashboard"]["board"]
                   if r["node_key"] == BUFFETS)
        self.assertIn("score_missing", row)
        for factor in row["score_missing"]:
            with self.subTest(factor):
                self.assertEqual(row["score_breakdown"][factor], 0.0)

    def test_the_factors_add_up_to_the_score_on_the_card(self) -> None:
        """The breakdown is the score taken apart, not numbers beside it."""
        client = FakeClient({"publish_market_overview": self.OVERVIEW})
        record = render.render_overview(client=client, period=PERIOD)
        for row in record["dashboard"]["board"]:
            with self.subTest(row["node_key"]):
                total = sum(v for k, v in row["score_breakdown"].items()
                            if k != scoring.RISK_KEY)
                total += row["score_breakdown"][scoring.RISK_KEY]
                self.assertAlmostEqual(row["category_score"], max(0.0, total),
                                       delta=0.5)

    def test_a_verdict_for_an_invented_node_is_dropped(self) -> None:
        client = FakeClient({"publish_market_overview": self.OVERVIEW})
        record = render.render_overview(client=client, period=PERIOD)
        self.assertIn(BUFFETS, record["dashboard"]["verdicts"])
        self.assertNotIn("9:9:9:9", record["dashboard"]["verdicts"])

    def test_the_model_is_shown_an_evidence_sheet_not_a_payload(self) -> None:
        client = FakeClient({"publish_market_overview": self.OVERVIEW})
        render.render_overview(client=client, period=PERIOD)
        prompt = client.prompt_for("publish_market_overview")
        self.assertIn("ev_price000001", prompt)
        self.assertNotIn("nodeLabelPathLocale", prompt)   # no raw vendor payload
        self.assertIn("ESTIMATE", prompt.replace("估算", "ESTIMATE"))

    def test_the_board_hands_the_model_the_alert_list(self) -> None:
        """Without the brief the model must invent risks or omit the section."""
        client = FakeClient({"publish_market_overview": self.OVERVIEW})
        render.render_overview(client=client, period=PERIOD)
        self.assertIn("RISK SIGNALS", client.prompt_for("publish_market_overview")
                      .replace("风险信号", "RISK SIGNALS"))

    def test_the_model_may_not_add_a_risk_of_its_own(self) -> None:
        client = FakeClient({"publish_market_overview": self.OVERVIEW})
        render.render_overview(client=client, period=PERIOD)
        instruction = "不得新增未列出的风险"
        self.assertIn(instruction, client.prompt_for("publish_market_overview"))

    def test_the_weights_ship_with_the_dashboard(self) -> None:
        client = FakeClient({"publish_market_overview": self.OVERVIEW})
        record = render.render_overview(client=client, period=PERIOD)
        self.assertEqual(record["dashboard"]["score_model"]["version"],
                         f"v{scoring.FORMULA_VERSION}")

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

    def test_a_vendor_status_is_named_rather_than_called_a_failure(self) -> None:
        """"模型调用失败" sends a reader to look for a bug. Each of these is a
        different thing for a person to go and do, and a board sat for weeks
        with no narrative on a 402 — an empty account, not a broken render."""
        for status, source in ((402, "no_balance"), (401, "auth"), (403, "auth"),
                               (429, "rate_limited"), (500, "error"), (None, "error")):
            with self.subTest(status=status):
                broken = FakeClient({})
                exc = RuntimeError("vendor said no")
                if status is not None:
                    exc.status_code = status
                broken.messages.create = mock.Mock(side_effect=exc)
                record = render.render_overview(client=broken, period=PERIOD)
                self.assertEqual(record["dashboard"]["narrative_source"], source)
                self.assertTrue(record["dashboard"]["board"])

    def test_an_answer_cut_off_by_the_budget_says_so(self) -> None:
        """A truncated response arrives as the half of the tool call the model
        had written. Its JSON does not parse, the client turns that into an
        empty object, and without the stop reason it is indistinguishable from
        a model that had nothing to say — so the board loses every word of
        narrative while reporting that nothing went wrong."""
        client = FakeClient({})
        client.messages.create = mock.Mock(
            return_value=mock.Mock(content=[], stop_reason="max_tokens"))
        record = render.render_overview(client=client, period=PERIOD)
        self.assertEqual(record["dashboard"]["narrative_source"], "truncated")
        self.assertTrue(record["dashboard"]["board"])

    def test_half_an_answer_is_flagged_even_though_it_parses(self) -> None:
        """It is missing sections nobody asked it to drop."""
        block = mock.Mock(type="tool_use", input={"thesis": "餐边柜仍是最好的方向。"})
        block.name = "publish_market_overview"
        client = FakeClient({})
        client.messages.create = mock.Mock(
            return_value=mock.Mock(content=[block], stop_reason="max_tokens"))
        record = render.render_overview(client=client, period=PERIOD)
        self.assertEqual(record["dashboard"]["narrative_source"], "truncated")
        self.assertIn("餐边柜", record["dashboard"]["thesis"])

    def test_the_answer_gets_room_for_every_block_it_must_emit(self) -> None:
        """One JSON object carrying a thesis, a verdict per tracked category,
        the movers, the direction read, the monitor summary and the selection
        picks. Six thousand tokens is not enough for that, and being cut off is
        silent — so the ceiling is a guarded number, not a default."""
        client = FakeClient({"publish_market_overview": self.OVERVIEW})
        spy = mock.Mock(side_effect=client._create)
        client.messages.create = spy
        render.render_overview(client=client, period=PERIOD)
        self.assertGreaterEqual(spy.call_args.kwargs["max_tokens"], 12_000)

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
        self.assertIn("RISK SIGNALS", client.prompt_for("publish_category_narrative")
                      .replace("风险信号", "RISK SIGNALS"))

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


class HeadlineTileTests(RenderTestCase):
    """The department headline: eight tiles, and no fraction that is really a gap
    report wearing a coverage label."""

    def tiles(self) -> dict[str, dict]:
        payload = render.build_overview("US", PERIOD, "zh")
        return {t["label"]: t for t in payload["headline"]["kpis"]}

    def test_the_headline_is_eight_tiles_in_two_rows_of_four(self) -> None:
        payload = render.build_overview("US", PERIOD, "zh")
        self.assertEqual(len(payload["headline"]["kpis"]), 8)

    def test_the_vendor_data_family_count_is_no_longer_a_headline(self) -> None:
        """The coverage strip below names every family and says which landed; a
        bare 12/22 at the top was a worry with nowhere to go."""
        self.assertNotIn("已覆盖数据类型", self.tiles())
        # The families themselves are still reported.
        payload = render.build_overview("US", PERIOD, "zh")
        self.assertEqual(payload["coverage"]["total"], len(panels.COVERAGE_FAMILIES))

    def test_every_tile_says_where_its_number_came_from(self) -> None:
        """An unmarked tile used to mean any of three things — measured, modelled,
        or computed here — and a reader cannot tell those apart. One chip on a
        board of seven silent tiles then reads as a page-wide hedge."""
        for surface, kpis in (
            ("overview", render.build_overview("US", PERIOD, "zh")["headline"]["kpis"]),
            ("category", render.build_category("US", BUFFETS, PERIOD, "zh")
             ["header"]["kpis"]),
        ):
            for tile in kpis:
                with self.subTest(surface, label=tile["label"]):
                    self.assertTrue(
                        tile["estimated"] or tile["observed"] or tile["computed"],
                        f"{tile['label']} carries no source")

    def test_a_tile_is_never_two_sources_at_once(self) -> None:
        for tile in render.build_overview("US", PERIOD, "zh")["headline"]["kpis"]:
            with self.subTest(label=tile["label"]):
                marks = sum(bool(tile[k]) for k in ("estimated", "observed", "computed"))
                self.assertEqual(marks, 1)

    def test_revenue_stays_modelled_on_a_closed_month(self) -> None:
        """A finished month does not turn a BSR inference into a measurement, and
        the hint has to say so or the chip reads as a complaint about freshness."""
        tile = self.tiles()["追踪类目月销售额"]
        self.assertTrue(tile["estimated"])
        self.assertIn("BSR", tile["hint"])
        self.assertIn("亚马逊不向任何人公开", tile["hint"])

    def test_the_measured_figures_are_marked_measured(self) -> None:
        """Price, listing counts and return rates are read, not inferred — and
        saying so is what stops the one modelled figure looking like the rule."""
        tiles = self.tiles()
        self.assertTrue(tiles["类目均价中位"]["observed"])
        self.assertTrue(tiles["已采集 listing"]["observed"])
        self.assertTrue(tiles["退货率高于同级的类目"]["observed"])

    def test_our_own_arithmetic_is_not_dressed_as_a_market_fact(self) -> None:
        tiles = self.tiles()
        self.assertTrue(tiles["最佳机会类目"]["computed"])
        self.assertTrue(tiles["高风险信号"]["computed"])

    def test_coverage_states_depth_not_a_count_over_a_count(self) -> None:
        """`2,016 / 505,758` compared listings read against listings reported, under
        a title about revenue. Two counts, and neither is a revenue denominator."""
        tile = self.tiles()["已采集 listing"]
        self.assertNotIn("/", tile["value"])
        self.assertEqual(tile["value"], "2")

    def test_the_depth_hint_says_whether_the_tail_was_exhausted(self) -> None:
        store.upsert_node_snapshot("US", BUFFETS, PERIOD, {"product_tail_pct": 0.2})
        self.assertIn("尾部无量", self.tiles()["已采集 listing"]["hint"])
        store.upsert_node_snapshot("US", BUFFETS, PERIOD, {"product_tail_pct": 7.5})
        self.assertIn("页数上限", self.tiles()["已采集 listing"]["hint"])

    def test_the_worst_tail_is_reported_not_the_average(self) -> None:
        """An average would let one exhausted category cover for a truncated one."""
        other = "1055398:1063306:1063308:3733251"      # Nightstands
        store.upsert_node_snapshot("US", BUFFETS, PERIOD, {"product_tail_pct": 0.1})
        store.upsert_node_snapshot("US", other, PERIOD,
                                   {"product_tail_pct": 9.0, "avg_price": 120.0,
                                    "total_revenue": 500_000.0},
                                   completeness=0.5, missing=[])
        store.upsert_product_metrics([
            {"marketplace": "US", "asin": "BX1", "period": PERIOD,
             "node_id_path": other, "price": 120.0, "revenue": 1_000.0,
             "source_tool": "product_research"}])
        self.assertIn("9.0%", self.tiles()["已采集 listing"]["hint"])

    def test_return_risk_drops_its_denominator_once_nothing_is_missing(self) -> None:
        """A fraction is for reporting a gap. With none, it says nothing."""
        tile = self.tiles()["退货率高于同级的类目"]
        self.assertNotIn("/", tile["value"])
        self.assertIn("全部已取到退货率", tile["hint"])

    def test_return_risk_keeps_the_denominator_while_data_is_missing(self) -> None:
        store.upsert_node_snapshot("US", "1055398:1063306:1063308:3733251", PERIOD,
                                   {"avg_price": 120.0, "total_revenue": 500_000.0},
                                   completeness=0.5, missing=[])
        tile = self.tiles()["退货率高于同级的类目"]
        self.assertEqual(tile["value"], "0 / 1")
        self.assertIn("仅 1/2", tile["hint"])

    def test_the_tracked_category_count_names_its_scope(self) -> None:
        """A share of the furniture root would be a share of the wrong denominator
        now that three other departments are in scope, and a wrong denominator is
        worse than none."""
        hint = self.tiles()["追踪子类目"]["hint"]
        self.assertIn("户外", hint)
        self.assertIn("遍历", hint)
        self.assertNotIn("%", hint)


class PriceCurveTests(RenderTestCase):
    """The price factor is scored against the department, not against a constant."""

    def test_one_curve_is_computed_and_shared_by_every_node(self) -> None:
        """Scoring each category against its own prices would be circular — a
        category is always perfectly priced for itself."""
        with mock.patch.object(scoring, "score_category",
                               wraps=scoring.score_category) as scored:
            render.build_overview("US", PERIOD, "zh")
        curves = {tuple(call.kwargs["aov_curve"]) for call in scored.call_args_list}
        self.assertEqual(len(curves), 1)

    def test_the_curve_comes_from_the_stored_price_bands(self) -> None:
        curve = panels.price_curve("US", PERIOD)
        # The seed's bands are 50-100 and 100-150; midpoints 75 and 125.
        self.assertEqual([round(price) for price, _fit in curve], [75, 125])

    def test_the_ui_is_given_the_curve_that_was_actually_used(self) -> None:
        payload = render.build_overview("US", PERIOD, "zh")
        self.assertEqual([row["price"] for row in payload["price_fit"]], [75, 125])

    def test_an_empty_warehouse_falls_back_and_shows_nothing(self) -> None:
        """A shipped constant presented as a reading is the thing to avoid."""
        db.reset_for_tests()
        taxonomy.ensure_nodes()
        store.upsert_node_snapshot("US", BUFFETS, PERIOD, {"avg_price": 450.0,
                                                           "total_revenue": 1_000.0},
                                   completeness=0.1, missing=[])
        payload = render.build_overview("US", PERIOD, "zh")
        self.assertEqual(payload["price_fit"], [])
        row = next(r for r in payload["board"] if r["node_key"] == BUFFETS)
        # Still scored, because a factor that zeroes for everyone deletes its weight.
        self.assertGreater(row["score_breakdown"]["aov_fit"], 0)

    def test_listings_outrank_the_vendor_bands_when_there_are_enough(self) -> None:
        """The vendor returns three or four bands and its top one is a property of
        its binning, not of the market."""
        store.upsert_products([{"marketplace": "US", "asin": f"BP{i}", "brand": "Demo",
                                "title": f"Listing {i}"} for i in range(40)])
        store.upsert_product_metrics([
            {"marketplace": "US", "asin": f"BP{i}", "period": PERIOD,
             "node_id_path": BUFFETS, "price": 800.0, "revenue": 500_000.0,
             "source_tool": "product_research"} for i in range(40)])
        curve = panels.price_curve("US", PERIOD)
        prices = [round(price) for price, _fit in curve]
        self.assertNotEqual(prices, [75, 125], "still reading the vendor bands")
        self.assertIn(800, prices)


class PriceBandLadderTests(unittest.TestCase):
    """The department chart's x-axis has to be a price axis.

    Vendor bins belong to the node: one category comes back cut 0-50/50-100 and
    the next 0-25/25-50/50-75. Summed by label they drew "0-100" beside "10-20",
    which is neither ordered nor non-overlapping — the same dollar described
    twice, with nothing on the chart saying so.
    """

    @staticmethod
    def band(key: str, products: float, revenue: float) -> dict:
        return {"bucket_key": key, "products": products, "units": products * 3,
                "revenue": revenue}

    def test_disagreeing_bins_are_recut_onto_one_ordered_ladder(self) -> None:
        bands = panels._rebin_price_bands([
            self.band("0-100", 10, 1_000.0), self.band("50-100", 40, 8_000.0),
            self.band("0-25", 5, 200.0), self.band("100-200", 30, 9_000.0),
            self.band("150-200", 20, 7_000.0),
        ])
        keys = [b["bucket_key"] for b in bands]
        self.assertEqual(keys, sorted(keys, key=lambda k: float(k.split("-")[0])))
        edges = [(float(k.split("-")[0]), float(k.split("-")[1])) for k in keys]
        for (_low, high), (next_low, _next_high) in zip(edges, edges[1:]):
            self.assertEqual(high, next_low, f"gap or overlap at {high}")

    def test_no_listing_is_lost_or_counted_twice(self) -> None:
        source = [self.band("0-100", 10, 1_000.0), self.band("50-150", 40, 8_000.0),
                  self.band("100-200", 30, 9_000.0)]
        bands = panels._rebin_price_bands(source)
        self.assertAlmostEqual(sum(b["products"] for b in bands),
                               sum(b["products"] for b in source), places=6)
        self.assertAlmostEqual(sum(b["revenue"] for b in bands),
                               sum(b["revenue"] for b in source), places=6)

    def test_a_thin_premium_band_survives_the_fold(self) -> None:
        """Ladder residue at the ends folds inward — but a top bin that is thin
        on listings and fat on revenue is the pocket this chart exists to find."""
        bands = panels._rebin_price_bands([
            self.band("20-50", 200, 20_000.0), self.band("50-100", 400, 50_000.0),
            self.band("100-200", 300, 60_000.0), self.band("800以上", 4, 30_000.0),
        ])
        self.assertEqual(bands[-1]["bucket_key"], "1000+",
                         "the open top band was dropped or given a made-up ceiling")
        self.assertGreater(bands[-1]["revenue"], 0)

    def test_a_band_with_no_numbers_in_it_is_left_off_the_price_axis(self) -> None:
        bands = panels._rebin_price_bands([
            self.band("20-50", 200, 20_000.0), self.band("50-100", 400, 50_000.0),
            self.band("100-200", 300, 60_000.0), self.band("unknown", 99, 99_000.0),
        ])
        self.assertAlmostEqual(sum(b["revenue"] for b in bands), 130_000.0, places=6)

    def test_agreeing_bins_are_kept_rather_than_coarsened(self) -> None:
        """Every node on the same binning is already an axis, and a finer one
        than the ladder: 100-150 and 150-200 should not become 100-200."""
        with mock.patch.object(panels.store, "get_distribution", return_value=[
            {"bucket_key": "50-100", "bucket_order": 0, "products": 20,
             "units": 60, "revenue": 1_000.0},
            {"bucket_key": "100-150", "bucket_order": 1, "products": 30,
             "units": 90, "revenue": 4_000.0},
            {"bucket_key": "150-200", "bucket_order": 2, "products": 10,
             "units": 30, "revenue": 5_000.0},
        ]):
            bands = panels._overview_price_bands(
                "US", PERIOD, [{"node_key": "a"}, {"node_key": "b"}])
        self.assertEqual([b["bucket_key"] for b in bands],
                         ["50-100", "100-150", "150-200"])
        self.assertEqual(bands[0]["products"], 40, "two nodes were not summed")
        self.assertAlmostEqual(sum(b["listing_share_pct"] for b in bands), 100.0, places=1)


class ElementNamingTests(RenderTestCase):
    """The model names and classifies mined terms; it computes and adds nothing."""

    NAMING = {"terms": [
        {"term": "fluted", "kind": "form", "label_zh": "竖纹", "label_en": "Fluted",
         "drop": False},
        {"term": "sideboard", "kind": "other", "label_zh": "", "label_en": "",
         "drop": True},
        {"term": "invented", "kind": "style", "label_zh": "凭空", "drop": False},
    ]}

    def seed(self) -> None:
        store.upsert_products([
            {"marketplace": "US", "asin": f"BN{i}", "brand": "Demo", "title": t}
            for i, t in enumerate(["Fluted Sideboard One", "Fluted Sideboard Two",
                                   "Fluted Sideboard Three"])])
        store.upsert_product_metrics([
            {"marketplace": "US", "asin": f"BN{i}", "period": PERIOD,
             "node_id_path": BUFFETS, "price": 399.0, "revenue": 100_000.0,
             "source_tool": "product_research"} for i in range(3)])

    def client(self) -> FakeClient:
        return FakeClient({"publish_element_naming": self.NAMING,
                           "publish_market_overview": {"thesis": "", "category_verdicts": []}})

    def test_naming_is_cached_so_it_is_asked_once_per_term(self) -> None:
        """Otherwise the call repeats on every render for the life of the month."""
        self.seed()
        client = self.client()
        render.render_overview(client=client, period=PERIOD)
        first = len([p for p in client.prompts if "MINED DESIGN TERMS" in p])
        render.render_overview(client=client, period=PERIOD)
        second = len([p for p in client.prompts if "MINED DESIGN TERMS" in p])
        self.assertEqual(first, 1)
        self.assertEqual(second, 1, "the second render must not re-ask")

    def test_a_term_named_under_an_older_vocabulary_is_asked_again(self) -> None:
        """`craft` and `color` were added after these rows were written. Trusting
        the cache would leave both columns empty except for terms the market
        happened to coin after the release."""
        self.seed()
        client = self.client()
        render.render_overview(client=client, period=PERIOD)
        with db.connect() as conn:
            conn.execute("UPDATE market_element_terms SET naming_version = 0")

        render.render_overview(client=client, period=PERIOD)

        asked = [p for p in client.prompts if "MINED DESIGN TERMS" in p]
        self.assertEqual(len(asked), 2)
        self.assertIn("fluted", asked[1])
        self.assertEqual(store.element_naming("US")["fluted"]["naming_version"],
                         elements.NAMING_VERSION)

    def test_a_long_term_list_is_asked_in_batches(self) -> None:
        """One call for 160 terms would ask for more output than the model can
        emit, and a truncated tool call parses as nothing at all — the whole
        month would come back unnamed rather than partly named."""
        client = self.client()
        terms = [{"term": f"term{i}", "asins": 4, "revenue_share_pct": 1.0,
                  "searches": 5_000} for i in range(elements.NAMING_BATCH * 2 + 1)]

        render.name_elements(client, "US", PERIOD, "zh", terms=terms)

        asked = [p for p in client.prompts if "MINED DESIGN TERMS" in p]
        self.assertEqual(len(asked), 3)
        # Every term reaches the model exactly once, and every one is recorded,
        # so none of them comes back "fresh" on the next render.
        for batch in asked:
            self.assertLessEqual(batch.count("term"), 400)
        cached = store.element_naming("US")
        self.assertEqual({t["term"] for t in terms} - set(cached), set())

    def test_one_failed_batch_does_not_discard_the_others(self) -> None:
        """Saving only at the end would make a blip halfway through cost every
        term that had already been classified."""
        client = self.client()
        calls = {"n": 0}
        real = client.messages.create

        def flaky(**kwargs):
            calls["n"] += 1
            if calls["n"] == 2:
                raise RuntimeError("boom")
            return real(**kwargs)

        client.messages.create = flaky
        terms = [{"term": f"word{i}", "asins": 4, "revenue_share_pct": 1.0,
                  "searches": 5_000} for i in range(elements.NAMING_BATCH * 2)]

        render.name_elements(client, "US", PERIOD, "zh", terms=terms)

        cached = store.element_naming("US")
        self.assertEqual(len(cached), elements.NAMING_BATCH,
                         "the surviving batch should still be cached")

    def test_a_term_the_model_skipped_is_still_recorded(self) -> None:
        """An unanswered term would otherwise look fresh forever."""
        self.seed()
        render.render_overview(client=self.client(), period=PERIOD)
        cached = store.element_naming("US")
        mined = {row["term"] for row in panels.mined_terms("US", PERIOD)}
        self.assertTrue(mined)
        self.assertEqual(mined - set(cached), set())

    def test_a_term_the_model_invented_is_not_stored(self) -> None:
        self.seed()
        render.render_overview(client=self.client(), period=PERIOD)
        self.assertNotIn("invented", store.element_naming("US"))

    def test_a_dropped_term_leaves_the_dashboard(self) -> None:
        self.seed()
        record = render.render_overview(client=self.client(), period=PERIOD)
        terms = {row["key"] for row in record["dashboard"]["elements"]}
        self.assertNotIn("sideboard", terms)

    def test_a_model_outage_does_not_cache_an_empty_answer(self) -> None:
        """A transient failure must not leave the month permanently unnamed."""
        self.seed()
        broken = FakeClient({})
        broken.messages.create = mock.Mock(side_effect=RuntimeError("boom"))
        render.render_overview(client=broken, period=PERIOD)
        self.assertEqual(store.element_naming("US"), {})

    def test_no_client_means_no_naming_and_no_crash(self) -> None:
        self.seed()
        record = render.render_overview(client=None, period=PERIOD)
        self.assertEqual(record["status"], "ok")
        # The terms are still mined and still carry their own words as labels.
        self.assertTrue(record["dashboard"]["elements"])


class EdgePhraseTests(RenderTestCase):
    """The per-ASIN traffic keywords were collected every month and never mined.

    ``flagship_keywords`` writes them to the edge table; the element read looked
    only at ``market_keyword_metrics``. The phrases were bought and then ignored.
    """

    def test_a_phrase_only_the_edge_table_holds_still_reaches_the_mining(self) -> None:
        store.upsert_products([
            {"marketplace": "US", "asin": f"BE{i}", "brand": "Demo",
             "title": t} for i, t in enumerate(
                 ["Boucle Accent Chair", "Boucle Swivel Chair", "Boucle Lounge Chair"])])
        store.upsert_product_metrics([
            {"marketplace": "US", "asin": f"BE{i}", "period": PERIOD,
             "node_id_path": BUFFETS, "price": 299.0, "revenue": 90_000.0,
             "source_tool": "product_research"} for i in range(3)])
        store.upsert_keyword_edges([
            {"marketplace": "US", "keyword": "boucle accent chair", "asin": f"BE{i}",
             "period": PERIOD, "searches": 14_000.0} for i in range(3)])

        mined = {row["term"] for row in panels.mined_terms("US", PERIOD)}

        self.assertIn("boucle", mined)

    def test_one_phrase_on_many_asins_is_one_phrase_worth_of_demand(self) -> None:
        """An edge's `searches` is the phrase's own volume, repeated per ASIN.
        Summing would multiply demand by however many listings rank for it."""
        store.upsert_keyword_edges([
            {"marketplace": "US", "keyword": "fluted sideboard", "asin": f"BX{i}",
             "period": PERIOD, "searches": 9_000.0} for i in range(3)])

        rows = store.keyword_edge_phrases("US", PERIOD)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["searches"], 9_000.0)

    def test_the_metrics_row_wins_because_only_it_carries_growth(self) -> None:
        """Growth is the axis that decides whether an element can be plotted, so
        a duplicate must not shadow the row that has it."""
        store.upsert_keyword_metrics([
            {"marketplace": "US", "keyword": "fluted sideboard", "period": PERIOD,
             "node_id_path": BUFFETS, "searches": 11_000.0, "searches_mom_pct": 24.0,
             "source_tool": "keyword_research"}])
        store.upsert_keyword_edges([
            {"marketplace": "US", "keyword": "fluted sideboard", "asin": "BY1",
             "period": PERIOD, "searches": 9_000.0}])

        rows = panels._demand_rows("US", PERIOD)

        matches = [r for r in rows if r["keyword"] == "fluted sideboard"]
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["searches_mom_pct"], 24.0)


class ComboMatrixTests(RenderTestCase):
    """The spec chart, built from stored rows only.

    These assertions were written against the per-attribute matrix that this
    chart replaced, and then re-pointed when y stopped being search growth. The
    unit changed; the invariants did not — an unmeasured axis is still `None`
    rather than zero, the rails still hold the half-measured specs, and the
    bounds still have floors.
    """

    # Each attribute word appears in more than one pairing on purpose. When two
    # words only ever occur together, `elements._dedupe` collapses them into the
    # bigram — which carries no kind of its own and so cannot enter a spec. That
    # is correct behaviour for the element read and a trap for this fixture.
    TITLES = ["Fluted Oak Sideboard", "Fluted Oak Console", "Fluted Oak Cabinet",
              "Fluted Oak Buffet", "Fluted Oak Credenza",
              "Fluted Walnut Hutch", "Fluted Walnut Dresser",
              # A second rated spec, so the board median has two ratings to sit
              # between and a gap has a sign worth asserting on.
              "Reeded Oak Chest", "Reeded Oak Vanity", "Reeded Oak Dresser",
              "Reeded Oak Highboy",
              # A third spec, on the shelf and with no rating of its own.
              "Reeded Walnut Sideboard", "Reeded Walnut Console",
              "Reeded Walnut Cabinet", "Reeded Walnut Buffet"]

    # By spec rather than by row number: the fixture grows and index arithmetic
    # silently re-labels whichever listing moved.
    RATINGS = {"Fluted Oak": 4.6, "Reeded Oak": 3.9}

    def setUp(self) -> None:
        super().setUp()
        self.seed()

    def seed(self) -> None:
        store.upsert_products([
            {"marketplace": "US", "asin": f"BC{i}", "brand": "Demo", "title": title}
            for i, title in enumerate(self.TITLES)])
        store.upsert_product_metrics([
            {"marketplace": "US", "asin": f"BC{i}", "period": PERIOD,
             "node_id_path": BUFFETS, "price": 399.0, "revenue": 100_000.0,
             "source_tool": "product_research", "ratings": 120.0,
             **({"rating": self._rating_for(title)}
                if self._rating_for(title) is not None else {})}
            for i, title in enumerate(self.TITLES)])
        # Phrases carrying the whole `fluted + oak` spec, and none for the other.
        store.upsert_keyword_metrics([
            {"marketplace": "US", "keyword": f"fluted oak {noun}", "period": PERIOD,
             "node_id_path": BUFFETS, "searches": 9_000.0, "searches_mom_pct": 24.0,
             "source_tool": "keyword_research"}
            for noun in ("sideboard", "console")])
        store.save_element_naming("US", [
            {"term": term, "kind": kind, "label": term, "label_zh": term,
             "label_en": term, "drop": False,
             "naming_version": elements.NAMING_VERSION}
            for term, kind in (("fluted", elements.CRAFT), ("reeded", elements.CRAFT),
                               ("oak", elements.MATERIAL),
                               ("walnut", elements.MATERIAL))])

    def _rating_for(self, title: str) -> float | None:
        return next((v for k, v in self.RATINGS.items() if title.startswith(k)), None)

    def matrix(self) -> dict:
        return render.build_overview("US", PERIOD, "zh")["element_combos"]

    def spec(self, key: str) -> dict:
        return next(p for p in self.matrix()["points"] if p["key"] == key)

    def test_both_axes_are_measured_from_stored_vendor_rows(self) -> None:
        point = self.spec("fluted+oak")
        self.assertGreater(point["shelf_pct"], 0)
        self.assertEqual(point["rating"], 4.6)
        self.assertEqual(point["asins"], 5)

    def test_the_y_axis_is_the_gap_to_the_board_median(self) -> None:
        """A bare 4.6 says nothing until you know what the shelf around it
        scores; the sign is the whole reading."""
        matrix = self.matrix()
        mid = matrix["bounds"]["y_mid"]
        liked = next(p for p in matrix["points"] if p["key"] == "fluted+oak")
        disliked = next(p for p in matrix["points"] if p["key"] == "reeded+oak")
        self.assertAlmostEqual(liked["rating_gap"], round(4.6 - mid, 2), places=2)
        self.assertGreater(liked["rating_gap"], disliked["rating_gap"])

    def test_the_rating_is_weighted_by_what_actually_sells(self) -> None:
        """The rating a shopper meets is the one on the listings taking the
        money, not the average of every listing naming the spec."""
        self.assertEqual(self.spec("reeded+oak")["rating"], 3.9)

    def test_the_quadrants_are_named_for_the_decision(self) -> None:
        quadrants = self.matrix()["quadrants"]
        self.assertEqual(len(quadrants), 4)
        self.assertIn("切入点", quadrants[2])

    def test_a_spec_with_no_rated_listing_is_railed_not_dropped(self) -> None:
        """Dropping it would hide "we sell this and nobody has said whether it
        is any good", which is a different claim from a zero."""
        point = self.spec("reeded+walnut")
        self.assertIsNotNone(point["shelf_pct"])
        self.assertIsNone(point["rating_gap"], "unmeasured, which is not zero")
        self.assertIsNone(point["rating"])

    def test_the_spec_is_broken_out_attribute_by_attribute(self) -> None:
        """A glued label reads as one long word; the hover card needs the parts."""
        parts = {p["kind"]: p["label"] for p in self.spec("fluted+oak")["spec"]}
        self.assertEqual(parts, {elements.CRAFT: "fluted",
                                 elements.MATERIAL: "oak"})

    def test_the_median_is_taken_over_specs_with_a_shelf_reading(self) -> None:
        matrix = self.matrix()
        shelves = [p["shelf_pct"] for p in matrix["points"]
                   if p["shelf_pct"] is not None]
        self.assertEqual(matrix["bounds"]["x_mid"], scoring._median(shelves))

    def test_the_dot_area_is_measured_against_the_largest_on_show(self) -> None:
        matrix = self.matrix()
        self.assertEqual(matrix["scale"]["max_revenue"],
                         max(p["revenue"] for p in matrix["points"]))

    def test_the_bounds_have_floors_so_noise_is_not_magnified(self) -> None:
        """Without them a chart whose specs sit within a point of each other is
        zoomed until those gaps look like findings."""
        bounds = self.matrix()["bounds"]
        self.assertGreaterEqual(bounds["x_max"] - bounds["x_min"], panels.MIN_X_SPAN)
        self.assertGreaterEqual(bounds["y_max"] - bounds["y_min"], panels.MIN_Y_SPAN)
        # And both reference lines reachable, or the chart draws a median it
        # cannot show.
        self.assertGreaterEqual(bounds["x_max"], bounds["x_mid"])
        self.assertLessEqual(bounds["x_min"], bounds["x_mid"])
        self.assertLessEqual(bounds["y_min"], 0.0)
        self.assertGreaterEqual(bounds["y_max"], 0.0)

    def test_every_spec_is_inside_the_frame(self) -> None:
        matrix = self.matrix()
        bounds = matrix["bounds"]
        for point in matrix["points"]:
            with self.subTest(point["key"]):
                if point["shelf_pct"] is not None:
                    self.assertLessEqual(point["shelf_pct"], bounds["x_max"])
                    self.assertGreaterEqual(point["shelf_pct"], bounds["x_min"])
                if point["rating_gap"] is not None:
                    self.assertGreaterEqual(point["rating_gap"], bounds["y_min"])
                    self.assertLessEqual(point["rating_gap"], bounds["y_max"])

    def test_the_tail_is_counted_even_when_it_is_not_drawn(self) -> None:
        """A chart saying nothing about what it left out is a chart that claims
        the market is the size of the chart."""
        with mock.patch.object(panels, "MAX_COMBO_POINTS", 1):
            matrix = self.matrix()
        self.assertEqual(len(matrix["points"]), 1)
        self.assertGreater(matrix["total"], 1)

    def test_a_dashboard_stored_before_this_axis_is_blanked_not_drawn(self) -> None:
        """The board is rendered on demand and a saved one can sit for days, so
        a deploy that changes an axis meets its own old payloads. Drawing them
        would rail every spec as "rating not measured" — a claim about the
        market rather than about the record."""
        stale = {"element_combos": {
            "points": [{"key": "fluted+oak", "shelf_pct": 1.2, "growth_pct": 24.0,
                        "searches": 9_000}],
            "bounds": {"x_max": 5.0, "x_mid": 1.0, "y_min": -25.0, "y_max": 25.0},
            "scale": {"max_searches": 9_000},
            "quadrants": ["a", "b", "c", "d"]}}
        panels.drop_stale_combos(stale)
        self.assertEqual(stale["element_combos"]["points"], [])
        self.assertIsNone(stale["element_combos"]["bounds"])

    def test_a_current_payload_survives_the_same_check(self) -> None:
        fresh = {"element_combos": self.matrix()}
        panels.drop_stale_combos(fresh)
        self.assertEqual(fresh["element_combos"]["points"], self.matrix()["points"])


NIGHTSTANDS = "1055398:1063306:1063308:3733251"
# Two colours across two looks, so no word is only ever seen inside one pairing:
# `elements._dedupe` collapses a term that always appears with the same
# neighbour into the bigram, and a bigram carries no kind of its own.
SHELF = {"Black Burl Sideboard": 6, "Black Glass Sideboard": 5,
         "Walnut Burl Sideboard": 5, "Walnut Glass Sideboard": 5}
SHELF_BEFORE = {"Black Burl Sideboard": 2, "Black Glass Sideboard": 6,
                "Walnut Burl Sideboard": 6, "Walnut Glass Sideboard": 6}
# Two listings each from the top two brands and one each from the rest, so "what
# the three largest brands left" is a number with a right answer.
SHELF_BRANDS = ["A", "A", "B", "C", "D", "E"]


def seed_shelf(period: str, shelf: dict, node: str, tag: str) -> None:
    """Listings with real looks in their titles, for one node and one month."""
    rows, metrics, index = [], [], 0
    for title, count in shelf.items():
        for i in range(count):
            asin = f"S{tag}{index}"
            index += 1
            rows.append({"marketplace": "US", "asin": asin, "title": title,
                         "brand": SHELF_BRANDS[i % len(SHELF_BRANDS)]})
            metrics.append({"marketplace": "US", "asin": asin, "period": period,
                            "node_id_path": node, "price": 300.0,
                            "revenue": 100_000.0, "rating": 4.2, "ratings": 120.0,
                            "source_tool": "product_research"})
    store.upsert_products(rows)
    store.upsert_product_metrics(metrics)


class ChartFrameTests(unittest.TestCase):
    """How the spec chart's frame is fitted to the specs in it.

    A fixed frame is what put every dot in the top-left corner of a real board:
    x ran to five points of head revenue while the busiest spec held two, and
    one spec rated a star and a half under the board owned five sixths of the
    height. The frame follows the distribution now, and a reading it cannot
    reach is pinned to the edge rather than dropped — so these tests are about
    where the axis stops, and about what it takes to make it stop short.

    Straight against the pure function: an outlier is a property of a
    distribution, and seeding forty-five listings to produce one would be a test
    of the fixture rather than of the frame.
    """

    @staticmethod
    def frame(shelves, gaps, *, x_mid=None):
        points = [{"shelf_pct": x, "rating_gap": y} for x, y in zip(shelves, gaps)]
        mid = x_mid if x_mid is not None else scoring._median(list(shelves))
        return panels._chart_bounds(points, mid, 4.5)

    @staticmethod
    def fill(lo, hi, values):
        """What share of the axis the readings inside it actually use."""
        inside = [v for v in values if lo <= v <= hi]
        return (max(inside) - min(inside)) / (hi - lo)

    def test_the_frame_follows_the_points_instead_of_a_fixed_span(self) -> None:
        """The complaint this answers: a board of small shares drawn against a
        five-point axis is mostly a picture of empty shelf."""
        shelves = [0.1 + i * 0.05 for i in range(40)]
        gaps = [round(-0.2 + i * 0.01, 2) for i in range(40)]
        bounds = self.frame(shelves, gaps)

        self.assertLess(bounds["x_max"], max(shelves) * 1.3)
        self.assertGreater(self.fill(bounds["x_min"], bounds["x_max"], shelves), 0.8)
        self.assertGreater(self.fill(bounds["y_min"], bounds["y_max"], gaps), 0.8)

    def test_one_detached_reading_stops_setting_the_axis(self) -> None:
        """A spec rated a star and a half under the board is a real reading and
        a terrible axis: it squeezes the other thirty-nine into a band."""
        gaps = [round(-0.2 + i * 0.01, 2) for i in range(40)]
        gaps[0] = -1.45
        bounds = self.frame([0.1 + i * 0.05 for i in range(40)], gaps)

        self.assertGreater(bounds["y_min"], -0.5)
        self.assertGreater(self.fill(bounds["y_min"], bounds["y_max"], gaps), 0.8)
        # Outside the frame, which is what the chart pins to the edge and draws
        # with an arrow — the point is not dropped, and the tick admits the cut.
        self.assertLess(gaps[0], bounds["y_min"])

    def test_an_even_tail_is_drawn_whole(self) -> None:
        """Shelf shares are Pareto-shaped: every step down the tail is a large
        fraction of what is left of it, and a frame that trims on that eats the
        four biggest specs on the board — the four the chart exists to show."""
        shelves = [0.15, 0.2, 0.25, 0.3, 0.4, 0.55, 0.7, 0.9, 1.2, 1.86]
        bounds = self.frame(shelves, [0.0] * len(shelves))

        self.assertGreaterEqual(bounds["x_max"], max(shelves))

    def test_the_trim_never_takes_more_than_a_tenth_of_the_points(self) -> None:
        """Otherwise a genuinely wide spread is drawn as its own middle."""
        shelves = [0.2 * (3 ** i) for i in range(12)]
        bounds = self.frame(shelves, [0.0] * len(shelves))

        outside = [v for v in shelves if v > bounds["x_max"]]
        self.assertLessEqual(len(outside),
                             int(len(shelves) * panels.MAX_TRIMMED_SHARE))

    def test_near_identical_specs_are_not_zoomed_into_weather(self) -> None:
        shelves = [0.4 + i * 0.001 for i in range(20)]
        bounds = self.frame(shelves, [round(i * 0.001, 3) for i in range(20)])

        self.assertGreaterEqual(bounds["x_max"] - bounds["x_min"], panels.MIN_X_SPAN)
        self.assertGreaterEqual(bounds["y_max"] - bounds["y_min"], panels.MIN_Y_SPAN)

    def test_a_spec_that_owns_the_shelf_is_pinned_not_obeyed(self) -> None:
        shelves = [0.2 + i * 0.05 for i in range(20)]
        shelves[0] = 22.0
        bounds = self.frame(shelves, [0.0] * 20)

        self.assertLess(bounds["x_max"], 5.0)
        self.assertGreater(self.fill(bounds["x_min"], bounds["x_max"], shelves), 0.6)

    def test_a_share_axis_keeps_zero_while_a_spec_is_near_it(self) -> None:
        """Holding none of the head is a real reading, so the frame does not cut
        the axis to win a few pixels. It lifts off zero only when every spec on
        the board sits well clear of it, and then the tick says where it
        starts."""
        near = self.frame([0.1 + i * 0.05 for i in range(20)], [0.0] * 20)
        clear = self.frame([12.0 + i * 0.5 for i in range(20)], [0.0] * 20)

        self.assertEqual(near["x_min"], 0.0)
        self.assertGreater(clear["x_min"], 0.0)

    def test_the_median_line_stays_inside_a_fitted_frame(self) -> None:
        """The median is taken over every measured spec, including the ones past
        the plot cap, so it can sit outside the points being drawn."""
        bounds = self.frame([0.1, 0.2, 0.3], [0.0, 0.0, 0.0], x_mid=9.0)

        self.assertGreaterEqual(bounds["x_max"], 9.0)


class QuadrantAxisTests(unittest.TestCase):
    """The opportunity quadrant's two axes.

    The quadrant sank: y was the spec's share movement against a plain zero, and
    a month whose walk collects more listings dilutes every spec at once, so all
    ninety dots dropped below the line and two of the four corners emptied. A
    quadrant with two empty corners is a scatter plot wearing a quadrant's
    caption. y is now signed against the median spec on the chart — the same
    thing x has always been — and the line carries the median's own value so a
    diluting department is stated rather than hidden.

    Straight against `_spec_map`: a board that all moved one way is a property
    of a month, and seeding two months of listings to manufacture one would be a
    test of the fixture rather than of the axis.
    """

    @staticmethod
    def chart(shifts, entries=None, *, revenue=None):
        entries = entries or [50.0 + i for i in range(len(shifts))]
        board = [{"node_key": "n", "label": "Buffets",
                  "node_label_path": "Home & Kitchen:Furniture:Buffets",
                  "return_risk": 0.0}]
        specs = [{"key": f"n|c{i}|l{i}", "node_key": "n",
                  "spec": [{"kind": "color", "kind_label": "颜色",
                            "label": f"c{i}"}],
                  "color": f"c{i}", "look": f"l{i}", "entry": entries[i],
                  "share_shift_pp": shift, "share_pct": 3.0,
                  "share_before_pct": None,
                  "revenue": (revenue or [1_000.0] * len(shifts))[i],
                  "asins": 9, "brands": 3, "avg_price": 200.0,
                  "rating": 4.2, "reviews": 80}
                 for i, shift in enumerate(shifts)]
        return panels._spec_map(specs, board, True, window=("202607", "202608"))

    def test_a_board_that_all_diluted_still_fills_both_halves(self) -> None:
        """The failure this axis replaces: every spec below the line, two
        corners empty, and a chart that cannot be read as a quadrant."""
        chart = self.chart([-2.4, -1.8, -1.1, -0.9, -0.4, -0.2, -0.1])
        gaps = [p["shift_gap_pp"] for p in chart["points"]]

        self.assertTrue(any(gap > 0 for gap in gaps), "nothing above the line")
        self.assertTrue(any(gap < 0 for gap in gaps), "nothing below it")
        # And the chart says out loud that the whole board diluted, instead of
        # letting the re-centring quietly turn a loss into an opening.
        self.assertLess(chart["bounds"]["y_mid"], 0)

    def test_the_line_carries_the_median_it_stands_for(self) -> None:
        shifts = [-2.4, -1.8, -1.1, -0.9, -0.4]
        chart = self.chart(shifts)

        self.assertEqual(chart["bounds"]["y_mid"], scoring._median(shifts))

    def test_the_raw_movement_survives_beside_the_gap(self) -> None:
        """The hover card and the model's sheet both quote the spec's own
        movement; the gap is a second reading of it, not a replacement."""
        chart = self.chart([-2.4, -1.8, 0.6])
        point = next(p for p in chart["points"] if p["share_shift_pp"] == 0.6)

        self.assertEqual(point["share_shift_pp"], 0.6)
        self.assertEqual(point["shift_gap_pp"],
                         round(0.6 - chart["bounds"]["y_mid"], 2))

    def test_a_shelf_with_no_comparison_month_has_no_gap_either(self) -> None:
        """Unmeasured is not zero on either reading of the number."""
        chart = self.chart([-1.0, None, 0.5])
        railed = next(p for p in chart["points"] if p["share_shift_pp"] is None)

        self.assertIsNone(railed["shift_gap_pp"])

    def test_the_entry_axis_follows_the_specs_not_a_floor(self) -> None:
        """It used to run to 65 whatever the board looked like, so a board of
        tight shelves spent a third of its width on nothing."""
        chart = self.chart([0.1] * 6, entries=[18.0, 22.0, 25.0, 28.0, 31.0, 34.0])
        bounds = chart["bounds"]

        self.assertLess(bounds["x_max"], 50.0)
        self.assertGreaterEqual(bounds["x_max"], 34.0)

    def test_the_entry_axis_stays_inside_nought_to_a_hundred(self) -> None:
        """0 and 100 are the ends of this scale: owned outright, and owned by
        nobody. Padding may not invent a shelf past either."""
        chart = self.chart([0.1] * 4, entries=[62.0, 78.0, 91.0, 99.0])

        self.assertLessEqual(chart["bounds"]["x_max"], 100.0)
        self.assertGreaterEqual(chart["bounds"]["x_min"], 0.0)

    def test_one_runaway_spec_does_not_flatten_the_rest(self) -> None:
        """Same fence as the spec chart: a spec that took eight points of its
        shelf is pinned to the top edge rather than owning the whole axis."""
        shifts = [-0.4, -0.2, -0.1, 0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 8.0]
        chart = self.chart(shifts)
        bounds = chart["bounds"]
        gaps = sorted(p["shift_gap_pp"] for p in chart["points"])
        inside = [gap for gap in gaps if bounds["y_min"] <= gap <= bounds["y_max"]]

        self.assertEqual(len(inside), len(gaps) - 1)
        self.assertGreater((max(inside) - min(inside))
                           / (bounds["y_max"] - bounds["y_min"]), 0.5)


def seed_product_lines() -> None:
    """Two months of shelves plus the naming the looks are read through.

    Shared by the quadrant tests and the selection-brief tests: both need the
    same thing — a board where some lines are open and rising and one shelf has
    no comparison month at all.
    """
    # Nightstands only exists this month: the board needs a snapshot for the node
    # to be ranked at all, and the chart has to rail it rather than draw a share
    # shift nobody could compute.
    store.upsert_node_snapshot("US", NIGHTSTANDS, PERIOD, {
        "total_revenue": 2_000_000.0, "avg_price": 189.0,
        "top5_brand_crn": 0.41}, completeness=0.4, missing=[])
    seed_shelf(PERIOD, SHELF, BUFFETS, "now")
    seed_shelf("202607", SHELF_BEFORE, BUFFETS, "was")
    seed_shelf(PERIOD, {"Black Burl Nightstand": 5}, NIGHTSTANDS, "night")
    store.save_element_naming("US", [
        {"term": term, "kind": kind, "label": term, "label_zh": term,
         "label_en": term, "drop": False,
         "naming_version": elements.NAMING_VERSION}
        for term, kind in (("black", elements.COLOR), ("walnut", elements.COLOR),
                           ("burl", elements.CRAFT), ("glass", elements.MATERIAL))])


class SpecMapTests(RenderTestCase):
    """The opportunity quadrant, over product lines rather than categories.

    It used to plot one dot per tracked category — the same rows the board
    above it lists, minus the ones whose growth could not be measured. A point
    here is what a design programme chooses between: a room, a shelf, a colour
    and a look, with both axes read off stored listings.
    """

    NIGHTSTANDS = NIGHTSTANDS

    def setUp(self) -> None:
        super().setUp()
        seed_product_lines()

    def chart(self) -> dict:
        return render.build_overview("US", PERIOD, "zh")["spec_map"]

    def point(self, key: str) -> dict:
        return next(p for p in self.chart()["points"] if p["key"] == key)

    def test_a_point_is_a_room_a_shelf_a_colour_and_a_look(self) -> None:
        """The four rows a brief names. A category alone cannot be drawn."""
        spec = self.point(f"{BUFFETS}|black|burl")["spec"]
        self.assertEqual([row["kind"] for row in spec],
                         ["area", "node", "color", "craft"])
        self.assertEqual([row["label"] for row in spec],
                         ["Kitchen & Dining Room Furniture", "Buffets & Sideboards",
                          "black", "burl"])

    def test_the_same_look_is_measured_once_per_shelf(self) -> None:
        """Burl in sideboards and burl in nightstands are different factories,
        different competitors and different money."""
        keys = {p["key"] for p in self.chart()["points"]}
        self.assertIn(f"{BUFFETS}|black|burl", keys)
        self.assertIn(f"{self.NIGHTSTANDS}|black|burl", keys)

    def test_the_y_axis_is_share_against_the_stored_previous_month(self) -> None:
        point = self.point(f"{BUFFETS}|black|burl")
        self.assertIsNotNone(point["share_before_pct"])
        self.assertGreater(point["share_shift_pp"], 0)
        self.assertEqual(self.chart()["window"], {"from": "202607", "to": PERIOD})

    def test_a_shelf_with_no_stored_previous_month_is_railed(self) -> None:
        """Unmeasured is not zero, and it is not a reason to leave a category
        off the chart either — which is what the category map did."""
        point = self.point(f"{self.NIGHTSTANDS}|black|burl")
        self.assertIsNone(point["share_shift_pp"])
        self.assertIsNotNone(point["entry"])

    def test_the_x_axis_is_what_the_three_largest_brands_left(self) -> None:
        # Six listings: A took two, B and C one each. Two of six are left.
        self.assertEqual(self.point(f"{BUFFETS}|black|burl")["entry"], 33.3)

    def test_the_divider_is_this_chart_s_median_not_a_fixed_fifty(self) -> None:
        """Three brands inside one colour of one shelf are not comparable to
        five brands across a whole category, so an absolute threshold here
        would be a number pretending to be one."""
        chart = self.chart()
        entries = sorted(p["entry"] for p in chart["points"])
        mid = (entries[len(entries) // 2] if len(entries) % 2
               else (entries[len(entries) // 2 - 1] + entries[len(entries) // 2]) / 2)
        self.assertAlmostEqual(chart["bounds"]["x_mid"], round(mid, 1), places=1)

    def test_the_rooms_are_shipped_for_the_filter(self) -> None:
        rooms = {a["area"]: a["count"] for a in self.chart()["areas"]}
        self.assertEqual(rooms.get("Bedroom Furniture"), 1)
        self.assertGreaterEqual(rooms.get("Kitchen & Dining Room Furniture", 0), 2)

    def test_the_category_map_is_not_shipped_alongside_it(self) -> None:
        """Two opportunity quadrants disagreeing about what an opening is would
        be worse than the one that was replaced."""
        self.assertNotIn("map", render.build_overview("US", PERIOD, "zh"))

    def test_the_plot_cap_is_spent_a_round_at_a_time(self) -> None:
        """A straight top-N by revenue spends the chart on the largest shelves
        and leaves the small categories off it — which is the complaint the
        category map earned, with six times as many points to spend."""
        crowded = ([{"node_key": "big", "revenue": 1_000 - i} for i in range(40)]
                   + [{"node_key": "small", "revenue": 4 - i} for i in range(2)])
        kept = panels._every_shelf_first(crowded, 12)
        self.assertEqual(len([p for p in kept if p["node_key"] == "small"]), 2)
        self.assertEqual(len(kept), 12)
        # Still revenue-ordered on the way out, so the chart draws big dots
        # under small ones rather than over them.
        self.assertEqual([p["revenue"] for p in kept],
                         sorted((p["revenue"] for p in kept), reverse=True))


class SelectionBriefTests(RenderTestCase):
    """The block the report opens with: what to put into development.

    Everything else on the board argues; this concludes. So the model is handed
    the product lines the shelf has actually built, the band the money sits in
    and the weight the freight has to carry — and what comes back is filtered by
    the same two rules the rest of the narrative lives under: it must name a
    node we track, and it must cite something.
    """

    NIGHTSTANDS = NIGHTSTANDS

    NARRATIVE = {
        "thesis": "餐边柜领跑 [ev_price000001](evidence:ev_price000001)。",
        "category_verdicts": [
            {"node_key": BUFFETS, "verdict": "enter", "rationale": "集中度低",
             "evidence_ids": ["ev_price000001"]},
        ],
        "selection": {
            "call": "本期把开发放在餐边柜的黑色木瘤纹上",
            "narrative": ("两条线共用一张 $200-300 的价格带和同一种贴皮工艺 "
                          "[ev_price000001](evidence:ev_price000001)，"
                          "先开餐边柜、床架等它的样本厚起来再说。"),
            "picks": [
                {"node_key": BUFFETS, "spec": "black · burl", "move": "enter",
                 "price_band": "$200-300", "envelope": "96.4 lb / 38,500 in³",
                 "fix": "门板对缝", "why_now": "前三品牌只拿走四成，份额还在涨",
                 "risk": "重量吃掉退货毛利", "evidence_ids": ["ev_price000001"]},
                # A shelf nobody collected.
                {"node_key": "9:9:9:9", "spec": "black · burl", "move": "enter",
                 "why_now": "invented", "evidence_ids": ["ev_price000001"]},
                # A pick whose evidence does not resolve.
                {"node_key": BUFFETS, "spec": "walnut · glass", "move": "watch",
                 "why_now": "uncited", "evidence_ids": ["ev_nothing00001"]},
            ],
            "avoid": [{"label": "Chairs · white · glass", "why": "拥挤且份额在退",
                       "evidence_ids": ["ev_price000001"]}],
        },
        "notes": [],
    }

    def setUp(self) -> None:
        super().setUp()
        seed_product_lines()

    def render(self, narrative: dict | None = None) -> dict:
        client = FakeClient({"publish_market_overview": narrative or self.NARRATIVE})
        self.client = client
        return render.render_overview(client=client, period=PERIOD)["dashboard"]

    def prompt(self) -> str:
        self.render()
        return self.client.prompt_for("publish_market_overview")

    def table(self, heading: str, prompt: str | None = None) -> list[dict]:
        """One brief block, parsed by column name.

        By name and not by position: the two tests that read a column out of
        this table indexed into it, so adding `area` to the row moved `corner`
        and both of them started asserting about a colour.
        """
        block = (prompt or self.prompt()).split(heading)[1].split("\n\n")[0]
        rows = [line for line in block.splitlines() if "|" in line]
        header = [cell.strip() for cell in rows[0].split("|")]
        return [dict(zip(header, [cell.strip() for cell in row.split("|")]))
                for row in rows[1:]]

    def test_the_model_is_shown_the_lines_the_shelf_has_built(self) -> None:
        """Without them it can only recommend a category, which is not a thing
        anybody can draw."""
        prompt = self.prompt()
        self.assertIn("PRODUCT LINES ON THE SHELF", prompt)
        self.assertIn("ease_of_entry", prompt)
        rows = self.table("PRODUCT LINES ON THE SHELF", prompt)
        first = rows[0]
        self.assertEqual(first["node_key"], BUFFETS)
        self.assertEqual((first["colour"], first["look"]), ("black", "burl"))

    def test_a_line_is_named_down_to_the_part_of_the_house(self) -> None:
        """The schema asks for 「area · shelf · colour · look」 and the table
        used to carry the last two. The model cannot copy a column it was
        never shown, so it wrote the shelf and left the programme generic."""
        rows = self.table("PRODUCT LINES ON THE SHELF")
        self.assertEqual(rows[0]["area"], "Kitchen & Dining Room Furniture")
        self.assertEqual(rows[0]["shelf"], "Buffets & Sideboards")

    def test_the_openings_are_the_rows_it_meets_first(self) -> None:
        """A model reads down a list. The lines it should be proposing from
        have to be at the top of it, not sorted in among the crowded ones."""
        corners = [row["corner"] for row in self.table("PRODUCT LINES ON THE SHELF")]
        # AHEAD rather than RISING: the corner is read against the same median
        # line the chart draws, so a line that diluted less than the board still
        # qualifies — and the header tells the model to say which it means.
        self.assertIn("OPEN+AHEAD", corners)
        self.assertEqual(corners[0], "OPEN+AHEAD")

    def test_a_pattern_outranks_a_material_at_the_same_standing(self) -> None:
        """Nearly every title names a material and almost none name a pattern,
        so on revenue alone the material rows took the top of the list and the
        brief recommended "black, made of glass" — true, and not a decision."""
        rows = self.table("PRODUCT LINES ON THE SHELF")
        kinds = [row["look_kind"] for row in rows]
        self.assertIn("craft", kinds)
        self.assertIn("material", kinds)
        self.assertLess(max(i for i, k in enumerate(kinds) if k == "craft"),
                        min(i for i, k in enumerate(kinds) if k == "material"))

    def test_the_signatures_say_which_elements_travel_together(self) -> None:
        """One look per line is what keeps a spec cell measurable, so a title
        naming both a pattern and a style is filed under the pattern and the
        style never appears beside it. The signatures are the other half of
        that trade, and they were charted but never shown to the model."""
        prompt = self.prompt()
        self.assertIn("SPEC SIGNATURES", prompt)
        rows = self.table("SPEC SIGNATURES", prompt)
        self.assertIn("burl · black", [row["signature"] for row in rows])
        self.assertTrue(all(int(row["attrs"]) >= 2 for row in rows),
                        "a one-attribute row is an element, not a signature")

    def test_the_model_is_shown_the_price_band_and_the_freight_envelope(self) -> None:
        """A pick states a price band and a weight. Both have to come off the
        warehouse, or the model writes the plausible one instead."""
        prompt = self.prompt()
        self.assertIn("PRICE BANDS", prompt)
        self.assertIn("PHYSICAL ENVELOPE AND RETURN COST", prompt)
        self.assertIn("96.4", prompt)

    def test_a_pick_survives_with_every_field_it_was_given(self) -> None:
        selection = self.render()["selection"]
        self.assertEqual(selection["call"], "本期把开发放在餐边柜的黑色木瘤纹上")
        pick = selection["picks"][0]
        self.assertEqual((pick["node_key"], pick["spec"], pick["move"]),
                         (BUFFETS, "black · burl", "enter"))
        self.assertEqual(pick["price_band"], "$200-300")
        self.assertEqual(pick["fix"], "门板对缝")
        self.assertEqual(pick["evidence_ids"], ["ev_price000001"])
        self.assertEqual(selection["avoid"][0]["label"], "Chairs · white · glass")

    def test_the_read_comes_through_with_its_citation(self) -> None:
        """The cards say what each line is; this says why this set, in this
        order. A selection decision does not fit in eight fields."""
        narrative = self.render()["selection"]["narrative"]
        self.assertIn("同一种贴皮工艺", narrative)
        self.assertIn("evidence:ev_price000001", narrative)

    def test_a_pick_for_a_shelf_we_do_not_track_is_dropped(self) -> None:
        """A recommendation about a market nobody read is worse than none."""
        picks = self.render()["selection"]["picks"]
        self.assertNotIn("9:9:9:9", [p["node_key"] for p in picks])

    def test_a_pick_whose_evidence_does_not_resolve_is_dropped(self) -> None:
        """The same rule the verdicts run on: an uncited claim is the failure
        mode this design exists to prevent."""
        picks = self.render()["selection"]["picks"]
        self.assertEqual(len(picks), 1)
        self.assertNotIn("walnut · glass", [p["spec"] for p in picks])

    def test_no_pick_means_no_block_rather_than_an_empty_heading(self) -> None:
        dashboard = self.render({**self.NARRATIVE, "selection": {"call": "本期无建议",
                                                                 "picks": []}})
        self.assertEqual(dashboard["selection"], {})

    def test_a_model_that_omits_the_block_entirely_is_not_an_error(self) -> None:
        dashboard = self.render({"thesis": "无。", "category_verdicts": [], "notes": []})
        self.assertEqual(dashboard["selection"], {})


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
