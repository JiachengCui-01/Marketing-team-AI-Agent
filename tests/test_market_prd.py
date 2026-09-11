"""PRD enforcement and the on-demand deep dive.

The PRD is where a model is most tempted to invent — it describes a product that
does not exist. These tests pin the rules that stop it, including the ones the
server applies whether or not the prompt was obeyed.
"""
from __future__ import annotations

import os
import unittest
from unittest import mock

from marketing_agent.tools.mcp_client import McpUnavailable
from server import db
from server.market import deepdive, evidence as ev, gateway, jobs, prd, store, taxonomy
from tests.test_market_render import BUFFETS, PERIOD, FakeClient, seed_warehouse


def index_with_ids(*ids: str) -> ev.EvidenceIndex:
    index = ev.EvidenceIndex(marketplace="US", period=PERIOD)
    for eid in ids:
        index.rows[eid] = {"id": eid, "metric": "x", "label": "x", "value_num": 1.0,
                           "unit": "", "period": PERIOD, "observed": True,
                           "quality": "ok", "subject_id": BUFFETS}
    return index


class EnforcementTests(unittest.TestCase):
    """``enforce`` is the belt to the prompt's braces, so it is tested without a model."""

    def setUp(self) -> None:
        self.index = index_with_ids("ev_known000001")

    def test_a_model_supplied_dimension_is_overwritten(self) -> None:
        document, _assumptions, _notes = prd.enforce(
            {"dimensions": [{"name": "宽度", "value": "60 英寸", "source": "to_confirm"}]},
            index=self.index)
        self.assertEqual(document["dimensions"][0]["value"], "[待确认 尺寸]")

    def test_a_competitor_spec_survives_only_with_a_live_citation(self) -> None:
        good = prd.enforce({"dimensions": [
            {"name": "宽度", "value": "60 x 16 x 32 inches", "source": "competitor_observed",
             "evidence_ids": ["ev_known000001"]}]}, index=self.index)[0]
        self.assertEqual(good["dimensions"][0]["value"], "60 x 16 x 32 inches")
        self.assertEqual(good["dimensions"][0]["source"], "competitor_observed")

        bad = prd.enforce({"dimensions": [
            {"name": "宽度", "value": "60 inches", "source": "competitor_observed",
             "evidence_ids": ["ev_invented001"]}]}, index=self.index)[0]
        self.assertEqual(bad["dimensions"][0]["value"], "[待确认 尺寸]")
        self.assertEqual(bad["dimensions"][0]["source"], "to_confirm")

    def test_load_and_assembly_are_always_placeholders(self) -> None:
        document = prd.enforce({
            "load_capacity": "承重 80 kg",
            "assembly": {"parts_count": "12", "est_minutes": "20"},
            "packaging": {"carton_plan": "双层瓦楞 1 箱"},
        }, index=self.index)[0]
        self.assertEqual(document["load_capacity"], "[待确认 承重]")
        self.assertEqual(document["assembly"]["parts_count"], "[待确认 组装件数]")
        self.assertEqual(document["assembly"]["est_minutes"], "[待确认 组装时长]")
        self.assertEqual(document["packaging"]["carton_plan"], "[待确认 箱规]")

    def test_cost_and_margin_are_always_placeholders_and_the_text_is_demoted(self) -> None:
        """A plausible landed cost is the most expensive hallucination this can ship."""
        document, assumptions, _notes = prd.enforce({"economics": {
            "target_landed_cost_range": "$120-$140 FOB",
            "target_gross_margin_range": "58%-62%",
        }}, index=self.index)
        self.assertEqual(document["economics"]["target_landed_cost_range"],
                         "[待确认 落地成本]")
        self.assertEqual(document["economics"]["target_gross_margin_range"],
                         "[待确认 毛利区间]")
        self.assertTrue(any("$120-$140 FOB" in a for a in assumptions))
        self.assertTrue(all(a.startswith("模型推断（未经证据支持）：") for a in assumptions))

    def test_an_unsupported_differentiator_is_forced_to_to_validate(self) -> None:
        document, _assumptions, notes = prd.enforce({"differentiators": [
            {"claim": "四角护角", "backing": "pain_point",
             "evidence_ids": ["ev_known000001"]},
            {"claim": "实木贴皮质感", "backing": "pain_point", "evidence_ids": []},
        ]}, index=self.index)
        backing = {d["claim"]: d["backing"] for d in document["differentiators"]}
        self.assertEqual(backing["四角护角"], "pain_point")
        self.assertEqual(backing["实木贴皮质感"], "to_validate")
        self.assertTrue(notes)

    def test_every_placeholder_gets_a_validation_row(self) -> None:
        document = prd.enforce({}, index=self.index)[0]
        questions = " ".join(row["question"] for row in document["validation_plan"])
        for key in ("dimensions", "materials", "load_capacity", "carton_plan",
                    "landed_cost", "gross_margin"):
            with self.subTest(key=key):
                self.assertIn(prd.PLACEHOLDERS[key][1], questions)

    def test_a_to_validate_hypothesis_also_earns_a_validation_row(self) -> None:
        document = prd.enforce({"differentiators": [
            {"claim": "隐藏走线孔", "backing": "to_validate", "evidence_ids": []}]},
            index=self.index)[0]
        self.assertTrue(any("隐藏走线孔" in row["question"]
                            for row in document["validation_plan"]))

    def test_a_model_written_validation_row_is_not_duplicated(self) -> None:
        document = prd.enforce({
            "validation_plan": [{"question": "确认整体尺寸与内部净空", "method": "打样"}],
        }, index=self.index)[0]
        matching = [r for r in document["validation_plan"]
                    if r["question"] == "确认整体尺寸与内部净空"]
        self.assertEqual(len(matching), 1)
        self.assertEqual(matching[0].get("method"), "打样")

    def test_missing_spec_sections_are_created_as_placeholders(self) -> None:
        """An absent section must not read as "no constraint"."""
        document = prd.enforce({}, index=self.index)[0]
        self.assertEqual(document["dimensions"][0]["value"], "[待确认 尺寸]")
        self.assertEqual(document["materials"][0]["material"], "[待确认 材质]")


class GenerationTests(unittest.TestCase):
    PRD_PAYLOAD = {
        "title": "60 英寸窄进深餐边柜",
        "positioning": "面向小户型餐厅的窄进深储物",
        "target_user": "美国小户型住户",
        "use_scenario": "餐厅与玄关之间的过渡收纳",
        "opportunity_basis": [{"claim": "中段价格带承接了多数销售额",
                               "evidence_ids": ["ev_price000001"]}],
        "target_price_band": "$429-$519",
        "price_rationale": "落在观测到的价格带内",
        "dimensions": [{"name": "宽度", "value": "60 英寸", "source": "to_confirm"}],
        "materials": [{"part": "柜体", "material": "实木贴皮", "source": "to_confirm"}],
        "load_capacity": "80 kg",
        "assembly": {"parts_count": "14", "est_minutes": "25"},
        "packaging": {"carton_plan": "1 箱", "fragile_points": ["柜门边缘"],
                      "evidence_ids": ["ev_price000001"]},
        "differentiators": [
            {"claim": "四角 EPE 护角", "backing": "pain_point",
             "evidence_ids": ["ev_price000001"]},
            {"claim": "实木贴皮质感", "backing": "pain_point", "evidence_ids": []},
        ],
        "economics": {"target_landed_cost_range": "$120-$140",
                      "target_gross_margin_range": "58%-62%"},
        "risks": [{"risk": "运输破损是首要退货动因", "kind": "return",
                   "evidence_ids": ["ev_price000001"]}],
        "validation_plan": [],
        "gaps": [],
    }

    def setUp(self) -> None:
        db.reset_for_tests()
        gateway.clear_cache()
        seed_warehouse()
        self.user = db.create_user(account="prd@example.com", password_hash="x",
                                   username="u", real_name="r", id_card="", avatar=None)

    def tearDown(self) -> None:
        db.reset_for_tests()

    def test_a_prd_is_generated_stored_and_user_scoped(self) -> None:
        client = FakeClient({prd.TOOL_NAME: self.PRD_PAYLOAD})
        record = prd.generate_prd(user_id=self.user["id"], node_id_path=BUFFETS,
                                  period=PERIOD, client=client)
        self.assertEqual(record["title"], "60 英寸窄进深餐边柜")
        self.assertEqual(store.get_prd(record["id"], self.user["id"])["id"], record["id"])
        self.assertIsNone(store.get_prd(record["id"], "someone-else"))

    def test_generation_makes_no_vendor_calls(self) -> None:
        client = FakeClient({prd.TOOL_NAME: self.PRD_PAYLOAD})
        with mock.patch.object(gateway.sellersprite, "call_tool") as vendor:
            prd.generate_prd(user_id=self.user["id"], node_id_path=BUFFETS,
                             period=PERIOD, client=client)
        vendor.assert_not_called()

    def test_the_stored_document_obeys_the_hard_rules(self) -> None:
        client = FakeClient({prd.TOOL_NAME: self.PRD_PAYLOAD})
        record = prd.generate_prd(user_id=self.user["id"], node_id_path=BUFFETS,
                                  period=PERIOD, client=client)
        document = record["prd"]
        self.assertEqual(document["dimensions"][0]["value"], "[待确认 尺寸]")
        self.assertEqual(document["economics"]["target_landed_cost_range"],
                         "[待确认 落地成本]")
        self.assertTrue(any("$120-$140" in a for a in record["assumptions"]))
        backing = {d["claim"]: d["backing"] for d in document["differentiators"]}
        self.assertEqual(backing["实木贴皮质感"], "to_validate")

    def test_the_server_score_rides_along_unchanged(self) -> None:
        client = FakeClient({prd.TOOL_NAME: self.PRD_PAYLOAD})
        record = prd.generate_prd(user_id=self.user["id"], node_id_path=BUFFETS,
                                  period=PERIOD, client=client)
        self.assertGreater(record["prd"]["opportunity"]["product_score"], 0)
        self.assertIn("score_breakdown", record["prd"]["opportunity"])

    def test_the_prompt_only_offers_competitor_specs_as_quotable(self) -> None:
        client = FakeClient({prd.TOOL_NAME: self.PRD_PAYLOAD})
        prd.generate_prd(user_id=self.user["id"], node_id_path=BUFFETS, period=PERIOD,
                         client=client)
        prompt = client.prompts[0]
        self.assertIn("COMPETITOR ATTRIBUTES", prompt)

    def test_a_category_without_a_snapshot_is_refused(self) -> None:
        client = FakeClient({prd.TOOL_NAME: self.PRD_PAYLOAD})
        with self.assertRaises(Exception):
            prd.generate_prd(user_id=self.user["id"], node_id_path="1:2:3",
                             period=PERIOD, client=client)

    def test_a_model_outage_still_yields_an_enforced_skeleton(self) -> None:
        broken = FakeClient({})
        broken.messages.create = mock.Mock(side_effect=RuntimeError("boom"))
        record = prd.generate_prd(user_id=self.user["id"], node_id_path=BUFFETS,
                                  period=PERIOD, client=broken)
        self.assertEqual(record["prd"]["source"], "error")
        self.assertEqual(record["prd"]["load_capacity"], "[待确认 承重]")


class DeepDiveTests(unittest.TestCase):
    def setUp(self) -> None:
        db.reset_for_tests()
        gateway.clear_cache()
        jobs.clear_review_cache()
        self._env = {k: os.environ.get(k) for k in
                     ("MARKETING_AGENT_TEST_LIVE_VENDOR", "SELLERSPRITE_SECRET_KEY")}
        os.environ["MARKETING_AGENT_TEST_LIVE_VENDOR"] = "1"
        os.environ["SELLERSPRITE_SECRET_KEY"] = "test-key"
        self._limits = dict(gateway.DAILY_LIMITS)
        gateway.DAILY_LIMITS[gateway.BUCKET_DEEPDIVE] = 200
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

    def _vendor(self):
        from tests.test_market_sweep import fixture_vendor
        return mock.patch.object(gateway.sellersprite, "call_tool",
                                 side_effect=fixture_vendor)

    def test_a_dive_fills_the_category_and_its_top_asins(self) -> None:
        with self._vendor():
            record = deepdive.run_deepdive(node_id_path=BUFFETS, period=PERIOD)
        self.assertIn(record["status"], ("complete", "partial"))
        self.assertGreater(record["calls_used"], 0)
        self.assertTrue(store.get_node_snapshot("US", BUFFETS, PERIOD))
        self.assertTrue(store.top_products("US", BUFFETS, PERIOD))
        asin_steps = [s for s in record["plan"] if s["subject_kind"] == "asin"]
        self.assertTrue(asin_steps)

    def test_the_second_asker_pays_nothing(self) -> None:
        with self._vendor():
            first = deepdive.run_deepdive(node_id_path=BUFFETS, period=PERIOD)
            spent = store.calls_used("US", gateway.run_date(), gateway.BUCKET_DEEPDIVE)
            second = deepdive.run_deepdive(node_id_path=BUFFETS, period=PERIOD)
        self.assertEqual(second["calls_used"], first["calls_used"])
        self.assertEqual(store.calls_used("US", gateway.run_date(),
                                          gateway.BUCKET_DEEPDIVE), spent)

    def test_a_tight_budget_yields_a_partial_dive_that_says_what_it_skipped(self) -> None:
        with self._vendor():
            record = deepdive.run_deepdive(node_id_path=BUFFETS, period=PERIOD,
                                           max_calls=3)
        self.assertEqual(record["status"], "partial")
        self.assertTrue(deepdive.skipped_steps(record))

    def test_the_deepdive_wallet_does_not_touch_the_sweep_wallet(self) -> None:
        with self._vendor():
            deepdive.run_deepdive(node_id_path=BUFFETS, period=PERIOD, max_calls=5)
        self.assertEqual(store.calls_used("US", gateway.run_date(),
                                          gateway.BUCKET_SWEEP), 0)
        self.assertGreater(store.calls_used("US", gateway.run_date(),
                                            gateway.BUCKET_DEEPDIVE), 0)

    def test_an_unknown_node_is_refused_before_anything_is_spent(self) -> None:
        with mock.patch.object(gateway.sellersprite, "call_tool") as vendor:
            with self.assertRaises(ValueError):
                deepdive.run_deepdive(node_id_path="9:9:9", period=PERIOD)
        vendor.assert_not_called()

    def test_a_transport_outage_marks_the_dive_failed(self) -> None:
        with mock.patch.object(gateway.sellersprite, "call_tool",
                               side_effect=McpUnavailable("down")):
            with self.assertRaises(McpUnavailable):
                deepdive.run_deepdive(node_id_path=BUFFETS, period=PERIOD)
        record = store.get_deepdive("US", BUFFETS, PERIOD)
        self.assertEqual(record["status"], "failed")

    def test_force_reruns_a_completed_dive(self) -> None:
        with self._vendor():
            deepdive.run_deepdive(node_id_path=BUFFETS, period=PERIOD, max_calls=4)
            before = store.calls_used("US", gateway.run_date(), gateway.BUCKET_DEEPDIVE)
            gateway.clear_cache()   # otherwise the process cache answers for free
            deepdive.run_deepdive(node_id_path=BUFFETS, period=PERIOD, force=True,
                                  max_calls=4)
        self.assertGreater(
            store.calls_used("US", gateway.run_date(), gateway.BUCKET_DEEPDIVE), before)


if __name__ == "__main__":
    unittest.main()
