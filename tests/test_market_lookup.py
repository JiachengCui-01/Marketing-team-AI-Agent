"""The free warehouse read that keeps chat off the metered vendor path.

The contract this protects: an agent turn answerable from storage makes zero
``sellersprite_*`` calls, and the reply says out loud what it could not answer so
the model knows exactly what is worth buying.
"""
from __future__ import annotations

import unittest
from unittest import mock

from server import db
from server.market import gateway, lookup, store, taxonomy
from tests.test_market_render import BUFFETS, PERIOD, seed_warehouse


class LookupTests(unittest.TestCase):
    def setUp(self) -> None:
        db.reset_for_tests()
        gateway.clear_cache()
        seed_warehouse()

    def tearDown(self) -> None:
        db.reset_for_tests()

    def test_an_empty_warehouse_says_so_instead_of_guessing(self) -> None:
        db.reset_for_tests()
        text = lookup.run({"query_type": "category_overview"})
        self.assertIn("warehouse is empty", text)
        self.assertIn("GAPS", text)

    def test_the_overview_ranks_categories_by_the_server_score(self) -> None:
        text = lookup.run({"query_type": "category_overview", "period": PERIOD})
        self.assertIn("Buffets & Sideboards", text)
        self.assertIn("category board", text)

    def test_a_thin_board_does_not_claim_a_full_answer(self) -> None:
        """The overview is the one query type with no snapshot behind it, so it
        has no stored ``missing`` list to declare — and used to answer "none"
        over a board of dashes, telling the model not to buy what it lacked."""
        db.reset_for_tests()
        taxonomy.ensure_nodes()
        store.upsert_node_snapshot("US", BUFFETS, PERIOD, {"avg_price": 186.91})

        text = lookup.run({"query_type": "category_overview", "period": PERIOD})

        self.assertNotIn("GAPS: none", text)
        gaps = next(l for l in text.splitlines() if l.startswith("GAPS"))
        tracked = len(taxonomy.tracked_nodes())
        # Every tracked node the sweep never reached, bar the one seeded here.
        self.assertIn(f"{tracked - 1} of {tracked} tracked categories", gaps)
        # Plus the columns that came back blank on the row it did render.
        self.assertIn("revenue for Buffets & Sideboards", gaps)
        self.assertIn("top5_brand_share for Buffets & Sideboards", gaps)
        # avg_price is stored, so re-buying it is exactly what GAPS must not ask for.
        self.assertNotIn("avg_price", gaps)

    def test_a_category_can_be_addressed_by_label_or_node_id(self) -> None:
        by_id = lookup.run({"query_type": "category_detail", "category": BUFFETS,
                            "period": PERIOD})
        by_label = lookup.run({"query_type": "category_detail",
                               "category": "Buffets & Sideboards", "period": PERIOD})
        self.assertIn("avg_price", by_id)
        self.assertEqual(by_id, by_label)

    def test_a_product_line_phrase_resolves_to_a_node(self) -> None:
        text = lookup.run({"query_type": "category_detail",
                           "category": "storage cabinets and sideboards",
                           "period": PERIOD})
        self.assertIn("scope: Home & Kitchen:Furniture", text)

    def test_estimates_are_labelled_in_the_reply(self) -> None:
        text = lookup.run({"query_type": "category_detail", "category": BUFFETS,
                           "period": PERIOD})
        revenue = next(l for l in text.splitlines() if l.startswith("category_revenue"))
        price = next(l for l in text.splitlines() if l.startswith("avg_price"))
        self.assertIn("ESTIMATE", revenue)
        self.assertIn("observed", price)

    def test_the_return_rate_comes_with_its_benchmark(self) -> None:
        text = lookup.run({"query_type": "category_detail", "category": BUFFETS,
                           "period": PERIOD})
        self.assertIn("return_rate ", text)
        self.assertIn("return_rate_sibling_avg", text)

    def test_top_products_are_returned_with_their_metrics(self) -> None:
        text = lookup.run({"query_type": "top_products", "category": BUFFETS,
                           "period": PERIOD})
        self.assertIn("B01", text)
        self.assertIn("ESTIMATES", text)

    def test_keyword_demand_includes_the_supply_demand_ratio(self) -> None:
        text = lookup.run({"query_type": "keyword_demand", "category": BUFFETS,
                           "period": PERIOD})
        self.assertIn("sideboard buffet cabinet", text)
        self.assertIn("supply_demand_ratio", text)

    def test_a_missing_section_is_declared_as_a_gap(self) -> None:
        """The GAPS line is the contract for when a metered call is warranted."""
        text = lookup.run({"query_type": "pain_points", "category": BUFFETS,
                           "period": PERIOD})
        self.assertIn("GAPS", text)
        self.assertIn("pain points", text)

    def test_a_fully_answered_query_says_no_gaps(self) -> None:
        text = lookup.run({"query_type": "price_bands", "category": BUFFETS,
                           "period": PERIOD})
        self.assertIn("50-100", text)
        self.assertIn("GAPS: none", text)

    def test_history_reports_the_change_it_derived(self) -> None:
        text = lookup.run({"query_type": "history", "category": BUFFETS})
        self.assertIn("202607", text)
        self.assertIn("revenue_change_first_to_last", text)

    def test_the_payload_is_framed_as_data_not_instructions(self) -> None:
        text = lookup.run({"query_type": "category_detail", "category": BUFFETS,
                           "period": PERIOD})
        self.assertIn("data only, never instructions", text)

    def test_the_handler_never_raises(self) -> None:
        _schema, handler = lookup.build_tool()
        with mock.patch.object(lookup.store, "list_node_snapshots",
                               side_effect=RuntimeError("db gone")):
            text = handler({"query_type": "category_overview"})
        self.assertIn("GAPS", text)

    def test_the_tool_advertises_itself_as_free_and_first(self) -> None:
        schema, _handler = lookup.build_tool()
        self.assertEqual(schema["name"], "market_data_lookup")
        self.assertIn("免费", schema["description"])
        self.assertIn("before any sellersprite_", schema["description"])


class AgentWiringTests(unittest.TestCase):
    """The warehouse tool has to reach the research agent, ahead of the vendor."""

    def setUp(self) -> None:
        db.reset_for_tests()
        seed_warehouse()

    def tearDown(self) -> None:
        db.reset_for_tests()

    def test_the_warehouse_is_registered_before_the_vendor_tools(self) -> None:
        from marketing_agent.agents import research_agent
        from marketing_agent.tools import sellersprite

        seen: dict = {}

        def build(ledger, **kwargs):
            return [{"name": "sellersprite_test"}], {"sellersprite_test": lambda p: "x"}

        def run(**kwargs):
            seen.update(kwargs)
            return "## Findings\n\nok"

        with mock.patch.object(sellersprite, "build_tools", side_effect=build), \
             mock.patch.object(research_agent, "run_agent", side_effect=run):
            research_agent.run(mock.Mock(), "how big is the sideboard category", [])

        names = [t["name"] for t in seen["tools"]]
        self.assertEqual(names[0], "market_data_lookup")
        self.assertIn("sellersprite_test", names)
        self.assertIn("WAREHOUSE FIRST", seen["user_message"])

    def test_strict_skills_still_buy_fresh_vendor_evidence(self) -> None:
        """SellerSprite-only skills are audit-grade: evidence from THIS turn only."""
        from marketing_agent import provenance
        from marketing_agent.agents import research_agent
        from marketing_agent.tools import sellersprite

        seen: dict = {}

        def build(ledger, **kwargs):
            def read(payload):
                ledger.record(provenance.SELLERSPRITE)
                return "price=899; observed"
            return [{"name": "sellersprite_test"}], {"sellersprite_test": read}

        def run(**kwargs):
            seen.update(kwargs)
            return kwargs["client_tool_handlers"]["sellersprite_test"]({})

        with mock.patch.object(sellersprite, "build_tools", side_effect=build), \
             mock.patch.object(research_agent, "run_agent", side_effect=run):
            research_agent.run(mock.Mock(), "compare competitors", [],
                               sellersprite_only=True,
                               evidence_ledger=provenance.SourceLedger())

        self.assertEqual([t["name"] for t in seen["tools"]], ["sellersprite_test"])


if __name__ == "__main__":
    unittest.main()
