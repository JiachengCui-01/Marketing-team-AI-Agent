"""Style and feature elements, and the follow / avoid lists built on them.

Runs on literals: the vocabulary is a constant and the aggregation is arithmetic,
so none of this needs a database, a vendor or a model.
"""
from __future__ import annotations

import unittest

from server.market import elements, gateway


def kw(keyword: str, searches: float, growth: float | None = None) -> dict:
    return {"keyword": keyword, "searches": searches, "searches_growth": growth}


class VocabularyTests(unittest.TestCase):
    def test_tokens_match_on_word_boundaries(self) -> None:
        """'cane' must not fire on 'canes' … or, worse, on 'hurricane lamp'."""
        rows = {r["key"] for r in elements.scan([kw("hurricane glass lamp", 5000)])}
        self.assertNotIn("rattan", rows)
        self.assertIn("glass", rows)

    def test_one_phrase_can_carry_several_elements(self) -> None:
        """A real search phrase is a spec: material, form and room at once."""
        rows = {r["key"] for r in elements.scan(
            [kw("fluted oak sideboard for entryway", 8000)])}
        self.assertEqual(rows, {"fluted", "oak", "entryway"})

    def test_every_vocabulary_entry_has_a_kind_we_label(self) -> None:
        for key, zh, en, kind, tokens in elements.VOCABULARY:
            with self.subTest(key):
                self.assertIn(kind, elements.KIND_LABELS)
                self.assertTrue(zh and en and tokens)

    def test_keys_are_unique(self) -> None:
        keys = [entry[0] for entry in elements.VOCABULARY]
        self.assertEqual(len(keys), len(set(keys)))


class AggregationTests(unittest.TestCase):
    def test_growth_is_search_weighted(self) -> None:
        """A 300% move on 40 searches is noise next to 12% on 40,000."""
        rows = elements.scan([kw("boucle sofa", 40_000, 0.12),
                              kw("boucle accent chair", 40, 3.0)])
        boucle = next(r for r in rows if r["key"] == "boucle")
        self.assertAlmostEqual(boucle["growth_pct"], 12.3, places=1)

    def test_our_own_two_months_beat_the_vendor_growth_column(self) -> None:
        rows = elements.scan(
            [kw("fluted cabinet", 10_000, 0.90), kw("fluted console", 6_000, 0.90)],
            previous=[kw("fluted cabinet", 8_000), kw("fluted console", 5_000)])
        fluted = next(r for r in rows if r["key"] == "fluted")
        # 25% and 20% against the stored month, not the vendor's 90%.
        self.assertAlmostEqual(fluted["growth_pct"], 23.1, places=1)

    def test_a_ratio_and_a_percentage_are_both_understood(self) -> None:
        """keyword_research reports growth as a ratio on some tools, a percent on
        others; nothing in this market grows 0.4% and bothers to report it."""
        ratio = elements.scan([kw("velvet sofa", 9_000, 0.25)])[0]["growth_pct"]
        percent = elements.scan([kw("velvet sofa", 9_000, 25.0)])[0]["growth_pct"]
        self.assertEqual(ratio, 25.0)
        self.assertEqual(percent, 25.0)

    def test_a_phrase_with_no_growth_anywhere_leaves_the_element_unrated(self) -> None:
        rows = elements.scan([kw("marble dining table", 9_000),
                              kw("marble console", 5_000)])
        marble = next(r for r in rows if r["key"] == "marble")
        self.assertIsNone(marble["growth_pct"])
        self.assertFalse(marble["rated"])


class GrowthWindowTests(unittest.TestCase):
    """Which window a growth number came from, and what must never be one.

    ``searches_growth`` used to be fed ``growth`` from keyword_research and
    ``searchRankGrowthRate`` from ABA — a yearly percentage and a *rank* movement
    ratio in the same column. A rank of 0.9951 read as "up 99.51%".
    """

    def test_a_rank_movement_is_never_read_as_demand_growth(self) -> None:
        row = {"keyword": "reacher", "searches": 10_115_226,
               "rank_growth_rate": 0.9951, "search_rank": 1, "rank_12w": 234}
        self.assertEqual(elements._growth_of(row, {}), (None, ""))

    def test_month_over_month_wins_over_year_over_year(self) -> None:
        """They disagree constantly in a seasonal category, which is the point."""
        row = {"keyword": "boucle sofa", "searches": 9_000,
               "searches_mom_pct": -8.13, "searches_yoy_pct": 18.31}
        value, window = elements._growth_of(row, {})
        self.assertEqual((value, window), (-8.13, elements.MOM))

    def test_a_stored_comparison_wins_over_both(self) -> None:
        row = {"keyword": "boucle sofa", "searches": 9_000,
               "searches_mom_pct": -8.13, "searches_yoy_pct": 18.31}
        value, window = elements._growth_of(row, {"boucle sofa": 6_000.0})
        self.assertEqual(window, elements.STORED)
        self.assertAlmostEqual(value, 50.0)

    def test_the_element_reports_the_window_its_volume_came_from(self) -> None:
        rows = elements.scan([
            kw("fluted cabinet", 10_000) | {"searches_mom_pct": 22.0},
            kw("fluted console", 2_000) | {"searches_yoy_pct": 90.0},
        ])
        fluted = next(r for r in rows if r["key"] == "fluted")
        self.assertEqual(fluted["window"], elements.MOM)


class ShelfShareTests(unittest.TestCase):
    """The supply half, matched on listing titles the product calls already paid for."""

    LISTINGS = [
        {"title": "Fluted Oak Sideboard Buffet", "revenue": 600_000.0, "price": 429.0},
        {"title": "Fluted Door Console Table", "revenue": 200_000.0, "price": 289.0},
        {"title": "Tufted Velvet Bench", "revenue": 100_000.0, "price": 199.0},
        {"title": "Plain Storage Cabinet", "revenue": 100_000.0, "price": 149.0},
    ]

    def test_share_is_of_revenue_not_of_listing_count(self) -> None:
        """Ten listings nobody buys prove a style is available, not that it works."""
        rows = {r["key"]: r for r in elements.shelf_share(self.LISTINGS)}
        self.assertEqual(rows["fluted"]["revenue_share_pct"], 80.0)
        self.assertEqual(rows["fluted"]["asins"], 2)
        self.assertEqual(rows["tufted"]["revenue_share_pct"], 10.0)

    def test_a_listing_counts_toward_every_element_it_carries(self) -> None:
        rows = {r["key"]: r for r in elements.shelf_share(self.LISTINGS)}
        self.assertEqual(rows["oak"]["revenue_share_pct"], 60.0)
        self.assertEqual(rows["fluted"]["revenue_share_pct"], 80.0)
        # Shares deliberately sum past 100: they are not slices of a pie.
        self.assertGreater(sum(r["revenue_share_pct"] for r in rows.values()), 100.0)

    def test_average_price_comes_from_the_matched_listings(self) -> None:
        rows = {r["key"]: r for r in elements.shelf_share(self.LISTINGS)}
        self.assertEqual(rows["fluted"]["avg_price"], 359.0)

    def test_a_thin_element_is_recorded_but_not_rated(self) -> None:
        rows = {r["key"]: r for r in elements.shelf_share(self.LISTINGS)}
        self.assertFalse(rows["tufted"]["shelf_rated"])
        self.assertEqual(rows["tufted"]["asins"], 1)

    def test_no_revenue_anywhere_produces_no_rows(self) -> None:
        """Dividing by a zero total would print 'nan%' on every tile."""
        self.assertEqual(elements.shelf_share(
            [{"title": "Fluted Cabinet", "revenue": 0.0}]), [])

    def test_an_untitled_listing_is_skipped_not_counted_as_plain(self) -> None:
        rows = elements.shelf_share(self.LISTINGS + [{"title": "", "revenue": 900_000.0}])
        fluted = next(r for r in rows if r["key"] == "fluted")
        # The untitled listing still enlarges the denominator — it is real revenue
        # we simply cannot attribute — so the share falls rather than holding.
        self.assertLess(fluted["revenue_share_pct"], 80.0)


class MergeTests(unittest.TestCase):
    def test_an_element_present_on_one_side_only_survives(self) -> None:
        """Search growth with no shelf presence is the most interesting cell there is."""
        demand = elements.scan([kw("japandi sideboard", 9_000, 0.4),
                                kw("japandi console", 5_000, 0.3)])
        shelf = elements.shelf_share([{"title": "Tufted Bench", "revenue": 10_000.0}])
        merged = {r["key"]: r for r in elements.merge(demand, shelf)}
        self.assertIn("japandi", merged)
        self.assertIn("tufted", merged)
        self.assertEqual(merged["japandi"]["revenue_share_pct"], 0.0)
        self.assertEqual(merged["tufted"]["searches"], 0)

    def test_both_halves_land_on_the_same_row(self) -> None:
        demand = elements.scan([kw("fluted cabinet", 9_000, 0.4),
                                kw("fluted console", 6_000, 0.3)])
        shelf = elements.shelf_share([
            {"title": "Fluted Oak Sideboard", "revenue": 600_000.0, "price": 429.0},
            {"title": "Fluted Console", "revenue": 400_000.0, "price": 289.0},
        ])
        fluted = next(r for r in elements.merge(demand, shelf) if r["key"] == "fluted")
        self.assertEqual(fluted["searches"], 15_000)
        self.assertEqual(fluted["revenue_share_pct"], 100.0)
        self.assertEqual(fluted["asins"], 2)


class EvidenceBarTests(unittest.TestCase):
    def test_a_single_phrase_is_never_a_trend(self) -> None:
        rows = elements.scan([kw("japandi sideboard", 50_000, 0.60)])
        rising, _falling = elements.split(rows)
        self.assertEqual(rising, [])

    def test_a_tiny_search_volume_is_never_a_trend(self) -> None:
        rows = elements.scan([kw("terrazzo console", 300, 0.80),
                              kw("terrazzo side table", 200, 0.75)])
        rising, _falling = elements.split(rows)
        self.assertEqual(rising, [])

    def test_a_move_inside_the_band_is_neither(self) -> None:
        rows = elements.scan([kw("oak sideboard", 20_000, 0.03),
                              kw("oak console table", 9_000, 0.02)])
        rising, falling = elements.split(rows)
        self.assertEqual((rising, falling), ([], []))

    def test_rising_and_falling_are_ordered_by_strength(self) -> None:
        rows = elements.scan([
            kw("fluted cabinet", 9_000, 0.40), kw("fluted console", 6_000, 0.35),
            kw("arched mirror cabinet", 8_000, 0.15), kw("arched bookcase", 5_000, 0.12),
            kw("tufted sofa", 12_000, -0.30), kw("tufted bench", 7_000, -0.25),
            kw("industrial shelf", 9_000, -0.14), kw("industrial desk", 6_000, -0.11),
        ])
        rising, falling = elements.split(rows)
        self.assertEqual([r["key"] for r in rising], ["fluted", "arched"])
        self.assertEqual([r["key"] for r in falling], ["tufted", "industrial"])


class BriefTests(unittest.TestCase):
    def test_an_empty_read_produces_no_block(self) -> None:
        """An empty heading in the prompt is worse than no heading."""
        self.assertEqual(elements.brief([], [], True), "")

    def test_the_brief_names_elements_and_their_evidence(self) -> None:
        rows = elements.scan([kw("fluted cabinet", 9_000, 0.40),
                              kw("fluted console", 6_000, 0.35)])
        rising, falling = elements.split(rows)
        text = elements.brief(rising, falling, True)
        self.assertIn("RISING fluted", text)
        self.assertIn("2 phrases", text)
        self.assertIn("15,000 searches", text)


class StepPeriodTests(unittest.TestCase):
    def test_stepping_back_over_a_year_boundary(self) -> None:
        self.assertEqual(gateway.step_period("202601", -1), "202512")
        self.assertEqual(gateway.step_period("202512", 1), "202601")
        self.assertEqual(gateway.step_period("202608", -1), "202607")

    def test_an_unusable_key_costs_the_comparison_not_the_render(self) -> None:
        for bad in ("", "nope", "2026", "202613", "202600", None):
            with self.subTest(bad):
                self.assertEqual(gateway.step_period(bad, -1), "")


if __name__ == "__main__":
    unittest.main()
