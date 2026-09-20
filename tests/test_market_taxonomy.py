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

    def test_every_product_line_has_a_way_in(self) -> None:
        """A line with no node at all is a line the system can never analyze.

        The two departments beyond furniture are entered through their roots and
        populated by the monthly walk, so the checked-in catalog carries a root for
        them rather than a hand-listed leaf — which still counts as a way in.
        """
        covered = {n["brand_category"] for n in taxonomy.TRACKED_NODES}
        for category in PRODUCT_CATEGORIES:
            with self.subTest(category=category):
                self.assertIn(category, covered)

    def test_every_scope_department_has_a_walk_root(self) -> None:
        """The walk is the only route to a leaf now, so a department with no root
        in it is a department that can never be collected."""
        labels = {n["node_id_path"]: n["node_label_path"].lower()
                  for n in taxonomy.TRACKED_NODES}
        for root in taxonomy.AREA_ROOTS:
            with self.subTest(root=root):
                self.assertIn(root, labels)
                self.assertTrue(taxonomy.in_scope(labels[root]))

    def test_catalog_paths_are_unique_and_inside_the_scope(self) -> None:
        """Scope, not the furniture tree: patio furniture and office seating sit in
        two other Amazon departments, which is why scoping to Furniture alone made
        them invisible."""
        paths = [n["node_id_path"] for n in taxonomy.TRACKED_NODES]
        self.assertEqual(len(paths), len(set(paths)))
        for node in taxonomy.TRACKED_NODES:
            with self.subTest(node=node["node_id_path"]):
                self.assertTrue(taxonomy.in_scope(node["node_label_path"]))
                self.assertTrue(any(node["node_id_path"].startswith(root)
                                    for root in taxonomy.AREA_ROOTS))

    def test_leaf_nodes_exclude_every_department_roll_up(self) -> None:
        """A roll-up is the sum of its own descendants; ranking one against them
        would put a total at the top of a list of parts."""
        leaves = {n["node_id_path"] for n in taxonomy.leaf_nodes()}
        for root in taxonomy.AREA_ROOTS:
            with self.subTest(root=root):
                self.assertNotIn(root, leaves)
        self.assertEqual(len(leaves),
                         len(taxonomy.TRACKED_NODES) - len(taxonomy.ROLLUP_PATHS))

    def test_tier_one_covers_every_furniture_product_line(self) -> None:
        """Tier 1 pays for the per-ASIN traffic and review packs, so a line with no
        tier-1 node never gets pain points.

        The three new departments enter at tier 2 deliberately: their leaves are
        discovered rather than chosen, and enrolling an unknown number of nodes at
        four extra calls each is how a month stops finishing. They are promoted by
        editing the catalog once the walk shows which leaves matter.
        """
        tier1 = {n["brand_category"] for n in taxonomy.TRACKED_NODES if n["tier"] == 1}
        for category in ("sofas and sectionals", "bed frames and headboards",
                         "dining tables and chairs",
                         "storage cabinets and sideboards", "desks",
                         "coffee and side tables"):
            with self.subTest(category=category):
                self.assertIn(category, tier1)

    def test_short_label_and_label_for(self) -> None:
        taxonomy.ensure_nodes()
        path = "1055398:1063306:3733781:3733831"
        self.assertEqual(taxonomy.short_label(taxonomy.label_for(path)), "Buffets & Sideboards")
        self.assertEqual(taxonomy.label_for("9:9:9"), "9:9:9")  # unknown falls back to the id

    def test_the_area_is_the_room_the_shelf_sits_in(self) -> None:
        """Read off the path, so a node the monthly walk enrols gets an area
        without anyone adding it to a table."""
        for label, area in (
            ("Home & Kitchen:Furniture:Kitchen & Dining Room Furniture:Buffets & Sideboards",
             "Kitchen & Dining Room Furniture"),
            ("Home & Kitchen:Furniture:Living Room Furniture:Tables:Coffee Tables",
             "Living Room Furniture"),
            ("Home & Kitchen:Furniture:Bedroom Furniture:Beds, Frames & Bases:Bed Frames",
             "Bedroom Furniture"),
            # A department root has no room above it and stands for its own.
            ("Patio, Lawn & Garden:Patio Furniture & Accessories",
             "Patio Furniture & Accessories"),
            ("", ""),
        ):
            with self.subTest(label=label):
                self.assertEqual(taxonomy.area_label(label), area)

    def test_every_tracked_node_has_an_area(self) -> None:
        """The chart groups by it, and a blank chip is not a room."""
        for node in taxonomy.TRACKED_NODES:
            with self.subTest(node=node["node_label_path"]):
                self.assertTrue(taxonomy.area_label(node["node_label_path"]))


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

    def test_parse_nodes_keeps_the_whole_scope(self) -> None:
        """Patio and Office rows are in scope now; Grocery still is not."""
        nodes = taxonomy.parse_nodes(fixture("product_node"))
        self.assertTrue(nodes)
        for node in nodes:
            self.assertTrue(taxonomy.in_scope(node["node_label_path"]))
        labels = " ".join(n["node_label_path"] for n in nodes)
        self.assertIn("Patio", labels)
        self.assertIn("Office Products", labels)

    def test_parse_nodes_rejects_what_is_out_of_scope(self) -> None:
        payload = json.dumps({"data": [
            {"nodeIdPath": "1:2", "nodeLabelPath": "Grocery:Paper Goods",
             "products": 9000}]})
        self.assertEqual(taxonomy.parse_nodes(payload), [])

    def test_a_seed_narrows_a_department_that_carries_more_than_furniture(self) -> None:
        """Office Products answers a seating query with filing cabinets too, and
        the department prefix alone cannot tell them apart."""
        payload = json.dumps({"data": [
            {"nodeIdPath": "o:1",
             "nodeLabelPath": "Office Products:Office Furniture & Lighting:Chairs",
             "products": 9000},
            {"nodeIdPath": "o:2",
             "nodeLabelPath": "Office Products:Office Furniture & Lighting:Filing Cabinets",
             "products": 9000}]})
        kept = {n["node_id_path"] for n in
                taxonomy.parse_nodes(payload, seed="office chairs seating")}
        self.assertEqual(kept, {"o:1"})

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
