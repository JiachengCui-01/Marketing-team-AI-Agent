"""The furniture browse-tree catalog and node resolution.

The node ids in ``taxonomy.TRACKED_NODES`` came from a live ``product_node`` reply
(checked in as a fixture), so these tests can assert on real paths offline.
"""
from __future__ import annotations

import json
import pathlib
import unittest

from marketing_agent.domain import PRODUCT_CATEGORIES
from server import db
from server.market import store, taxonomy

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "sellersprite"


def fixture(name: str) -> str:
    return (FIXTURES / f"{name}.json").read_text(encoding="utf-8")


class CatalogTests(unittest.TestCase):
    def setUp(self) -> None:
        db.reset_for_tests()

    def tearDown(self) -> None:
        db.reset_for_tests()

    def test_bootstrap_costs_no_vendor_calls(self) -> None:
        """Node ids are stable for years; the old sweep re-bought them every run."""
        self.assertEqual(taxonomy.ensure_nodes(), len(taxonomy.TRACKED_NODES))
        self.assertEqual(len(store.list_nodes("US")), len(taxonomy.TRACKED_NODES))

    def test_ensure_nodes_is_idempotent(self) -> None:
        taxonomy.ensure_nodes()
        taxonomy.ensure_nodes()
        self.assertEqual(len(store.list_nodes("US")), len(taxonomy.TRACKED_NODES))

    def test_tracked_nodes_bootstrap_on_first_read(self) -> None:
        self.assertEqual(len(taxonomy.tracked_nodes()), len(taxonomy.TRACKED_NODES))

    def test_every_product_line_has_at_least_one_node(self) -> None:
        """A product line with no node is a line the system can never analyze."""
        covered = {n["brand_category"] for n in taxonomy.TRACKED_NODES}
        for category in PRODUCT_CATEGORIES:
            with self.subTest(category=category):
                self.assertIn(category, covered)

    def test_catalog_paths_are_unique_and_inside_the_furniture_tree(self) -> None:
        paths = [n["node_id_path"] for n in taxonomy.TRACKED_NODES]
        self.assertEqual(len(paths), len(set(paths)))
        for node in taxonomy.TRACKED_NODES:
            with self.subTest(node=node["node_id_path"]):
                self.assertTrue(taxonomy.is_furniture(node["node_label_path"]))
                self.assertTrue(node["node_id_path"].startswith(taxonomy.FURNITURE_ROOT))

    def test_leaf_nodes_exclude_the_department_roll_up(self) -> None:
        """The root is the sum of the categories; ranking it against them is nonsense."""
        leaves = {n["node_id_path"] for n in taxonomy.leaf_nodes()}
        self.assertNotIn(taxonomy.FURNITURE_ROOT, leaves)
        self.assertEqual(len(leaves), len(taxonomy.TRACKED_NODES) - 1)

    def test_tier_one_covers_every_product_line(self) -> None:
        """Tier 1 pays for the expensive traffic and review packs, so a line with
        no tier-1 node would never get pain points."""
        tier1 = {n["brand_category"] for n in taxonomy.TRACKED_NODES if n["tier"] == 1}
        for category in PRODUCT_CATEGORIES:
            with self.subTest(category=category):
                self.assertIn(category, tier1)

    def test_short_label_and_label_for(self) -> None:
        taxonomy.ensure_nodes()
        path = "1055398:1063306:3733781:3733831"
        self.assertEqual(taxonomy.short_label(taxonomy.label_for(path)), "Buffets & Sideboards")
        self.assertEqual(taxonomy.label_for("9:9:9"), "9:9:9")  # unknown falls back to the id


class NodeResolutionTests(unittest.TestCase):
    def test_pick_node_prefers_home_furniture_over_office(self) -> None:
        picked = taxonomy.pick_node(fixture("product_node"), "sofas and sectionals")
        self.assertIsNotNone(picked)
        self.assertTrue(taxonomy.is_furniture(picked[1]))

    def test_pick_node_uses_keyword_tokens_within_the_right_tree(self) -> None:
        picked = taxonomy.pick_node(fixture("product_node"), "bedroom furniture")
        self.assertIn("Bedroom Furniture", picked[1])

    def test_pick_node_refuses_rather_than_guessing(self) -> None:
        payload = json.dumps({"data": [
            {"nodeIdPath": "1:2", "nodeLabelPath": "Grocery:Paper Goods", "products": 9000}]})
        self.assertIsNone(taxonomy.pick_node(payload, "sofas and sectionals"))

    def test_pick_node_tolerates_junk(self) -> None:
        self.assertIsNone(taxonomy.pick_node("not json", "desks"))
        self.assertIsNone(taxonomy.pick_node(json.dumps({"data": []}), "desks"))

    def test_parse_nodes_keeps_only_the_furniture_subtree(self) -> None:
        nodes = taxonomy.parse_nodes(fixture("product_node"))
        self.assertTrue(nodes)
        for node in nodes:
            self.assertTrue(taxonomy.is_furniture(node["node_label_path"]))
        # The fixture deliberately includes Patio and Office rows.
        raw = json.loads(fixture("product_node"))["data"]
        self.assertLess(len(nodes), len(raw))

    def test_parse_nodes_marks_catalog_membership(self) -> None:
        nodes = {n["node_id_path"]: n for n in taxonomy.parse_nodes(fixture("product_node"))}
        root = nodes.get(taxonomy.FURNITURE_ROOT)
        self.assertIsNotNone(root)
        self.assertTrue(root["tracked"])
        untracked = [n for n in nodes.values() if not n["tracked"]]
        self.assertTrue(untracked, "the fixture should contain nodes outside the catalog")

    def test_brand_category_prefers_the_catalog(self) -> None:
        self.assertEqual(
            taxonomy.brand_category_for(
                "Home & Kitchen:Furniture:Kitchen & Dining Room Furniture:Buffets & Sideboards"),
            "storage cabinets and sideboards")

    def test_brand_category_falls_back_to_the_product_vocabulary(self) -> None:
        self.assertEqual(
            taxonomy.brand_category_for("Home & Kitchen:Furniture:Something:Writing Desks"),
            "desks")
        self.assertIsNone(
            taxonomy.brand_category_for("Home & Kitchen:Furniture:Something:Wall Art"))


if __name__ == "__main__":
    unittest.main()
