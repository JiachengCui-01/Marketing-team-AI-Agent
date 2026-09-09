from types import SimpleNamespace
import unittest
from unittest import mock

from marketing_agent import provenance
from marketing_agent.agents import research_agent
from marketing_agent.conversation import Conversation
from marketing_agent.oa import agent
from marketing_agent.tools import sellersprite, web_search
from server import marketing_skills


class StrictSourceTests(unittest.TestCase):
    def test_empty_json_envelopes_are_not_evidence_but_zero_metrics_are(self):
        for payload in ('[]', '{}', 'null', '{"data": [], "total": 0}',
                        '{"data": {"records": [], "page": 1}}', '{"success": false, "message": "denied"}'):
            self.assertFalse(sellersprite._has_data(payload), payload)
        self.assertTrue(sellersprite._has_data('{"data": [{"sales": 0, "asin": "B01"}]}'))

    def test_built_in_skills_enable_policy_without_affecting_custom_skills(self):
        for skill in ("competitive-positioning-brief", "product-launch-campaign"):
            self.assertTrue(marketing_skills.requires_sellersprite_only([skill]))
        self.assertFalse(marketing_skills.requires_sellersprite_only(["custom"]))
        self.assertFalse(marketing_skills.requires_sellersprite_only([]))

    def test_vendor_unavailable_never_starts_web_or_model(self):
        with mock.patch.object(sellersprite, "build_tools", return_value=([], {})), \
                mock.patch.object(web_search, "is_available") as web, \
                mock.patch.object(research_agent, "run_agent") as run:
            result = research_agent.run(mock.Mock(), "竞品分析", ["sofas"], sellersprite_only=True)
        web.assert_not_called()
        run.assert_not_called()
        self.assertIn("数据缺口", result)

    def test_no_vendor_call_discards_unsupported_model_analysis(self):
        with mock.patch.object(sellersprite, "build_tools", return_value=([{"name": "sellersprite_test"}], {})), \
                mock.patch.object(research_agent, "run_agent", return_value="Guaranteed 1000 sales"):
            result = research_agent.run(mock.Mock(), "compare", [], sellersprite_only=True)
        self.assertNotIn("1000", result)

    def test_only_vendor_tools_available_and_actual_evidence_is_propagated(self):
        evidence = provenance.SourceLedger()

        def build(ledger, **kwargs):
            def read(payload):
                ledger.record(provenance.SELLERSPRITE)
                return "price=899; ASIN=B01; observed; E01"
            return [{"name": "sellersprite_test"}], {"sellersprite_test": read}

        def run(**kwargs):
            self.assertEqual([t["name"] for t in kwargs["tools"]], ["sellersprite_test"])
            self.assertEqual(set(kwargs["client_tool_handlers"]), {"sellersprite_test"})
            return kwargs["client_tool_handlers"]["sellersprite_test"]({})

        with mock.patch.object(sellersprite, "build_tools", side_effect=build), \
                mock.patch.object(research_agent, "run_agent", side_effect=run):
            result = research_agent.run(mock.Mock(), "compare tariffs and Wayfair", [],
                                        sellersprite_only=True, evidence_ledger=evidence)
        self.assertIn("E01", result)
        self.assertEqual(evidence.used, [provenance.SELLERSPRITE])

    def test_copilot_cannot_synthesize_without_evidence_or_offer_other_sources(self):
        response = SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text="Sales will double")])
        create = mock.Mock(return_value=response)
        client = SimpleNamespace(messages=SimpleNamespace(create=create))
        with mock.patch.object(agent, "build_oa_handlers", return_value={}):
            result = agent.run_oa_copilot(client, Conversation(), "新品计划", sellersprite_only=True)
        self.assertNotIn("double", result)
        self.assertEqual({t["name"] for t in create.call_args.kwargs["tools"]},
                         {"delegate_to_research_agent", "delegate_to_content_agent"})

    def test_combined_skill_text_keeps_both_complete_references(self):
        text = marketing_skills.build_skill_addendum(["competitive-positioning-brief", "product-launch-campaign"])
        for sid, ref in (("competitive-positioning-brief", "comparison-template.md"),
                         ("product-launch-campaign", "checklist.md")):
            content = marketing_skills._read(marketing_skills.SKILLS_DIR / sid / "references" / ref)
            self.assertIn(content, text)
        self.assertLess(len(text), marketing_skills.MAX_SKILL_TEXT_CHARS)

    def test_research_evidence_reaches_content_even_if_model_omits_it(self):
        def tool(name, number):
            return SimpleNamespace(stop_reason="tool_use", content=[SimpleNamespace(
                type="tool_use", id=str(number), name=name, input={"task": "prepare report"})])
        responses = [tool("delegate_to_research_agent", 1), tool("delegate_to_content_agent", 2),
                     SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text="Report E01")])]
        client = SimpleNamespace(messages=SimpleNamespace(create=mock.Mock(side_effect=responses)))

        def dispatch(client, name, payload, **kwargs):
            self.assertTrue(kwargs["sellersprite_only"])
            if name == "delegate_to_research_agent":
                kwargs["evidence_ledger"].record(provenance.SELLERSPRITE)
                return "E01: ASIN B01 observed price 899, retrieved at test-time"
            self.assertIn("E01: ASIN B01 observed price 899", payload["task"])
            return "Draft based on E01"

        with mock.patch.object(agent, "build_oa_handlers", return_value={}), \
                mock.patch.object(agent, "_dispatch", side_effect=dispatch):
            result = agent.run_oa_copilot(client, Conversation(), "report", sellersprite_only=True)
        self.assertIn("Report E01", result)
        self.assertIn("SellerSprite market data", result)


if __name__ == "__main__":
    unittest.main()
