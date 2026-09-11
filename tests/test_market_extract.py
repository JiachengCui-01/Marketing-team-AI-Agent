"""Payload → rows → evidence, against real captured replies.

Every fixture in ``tests/fixtures/sellersprite/`` is a trimmed copy of a live
SellerSprite reply for one furniture node, so these assertions pin the actual
vendor contract rather than a guess about it.
"""
from __future__ import annotations

import json
import pathlib
import unittest

from server.market import extract
from server.market.evidence import EvidenceIndex

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "sellersprite"
NODE = "1055398:1063306:3733781:3733831"
PERIOD = "202608"


class Reply:
    """The slice of ``gateway.VendorReply`` the extractors read."""

    def __init__(self, name: str) -> None:
        self.tool = name
        self.payload = (FIXTURES / f"{name}.json").read_text(encoding="utf-8")
        self.call_id = f"call_{name}"
        self.arguments = {"request": {"nodeIdPath": NODE, "month": PERIOD}}


class ScalarTests(unittest.TestCase):
    def test_percent_fields_become_fractions(self) -> None:
        """returnRatio 1.5674 means 1.57%, top5BrandCrn 0.3929 means 39.29% — the
        same quantity in two scales, so one of them has to be normalised."""
        self.assertAlmostEqual(extract.ratio(1.5674, field="returnRatio"), 0.015674)
        self.assertAlmostEqual(extract.ratio(0.3929, field="top5BrandCrn"), 0.3929)
        self.assertAlmostEqual(extract.ratio(45.0, field="newProductProportion"), 0.45)

    def test_weight_strings_parse_to_pounds(self) -> None:
        self.assertAlmostEqual(extract.pounds("75.4 pounds"), 75.4)
        self.assertAlmostEqual(extract.pounds("2 kg"), 4.40924, places=4)
        self.assertAlmostEqual(extract.pounds("16 ounces"), 1.0)
        self.assertIsNone(extract.pounds(None))

    def test_every_vendor_month_spelling_normalises(self) -> None:
        self.assertEqual(extract.month_key("2026.08"), "202608")   # keyword_research
        self.assertEqual(extract.month_key("202608"), "202608")    # aba_research_monthly
        self.assertEqual(extract.month_key("2025-08"), "202508")   # asin_prediction
        self.assertEqual(extract.month_key("2025-08-01"), "202508")  # demand trend
        self.assertEqual(extract.month_key(None), "")

    def test_epoch_milliseconds_become_dates(self) -> None:
        self.assertEqual(extract.epoch_date(1745366400000), "2025-04-23")
        self.assertEqual(extract.epoch_date(None), "")

    def test_months_since_measures_listing_age(self) -> None:
        self.assertEqual(extract.months_since("2025-04-23", reference="202608"), 16)
        self.assertIsNone(extract.months_since(""))

    def test_number_survives_vendor_formatting(self) -> None:
        self.assertAlmostEqual(extract.number("$1,019.99"), 1019.99)
        self.assertIsNone(extract.number(None))
        self.assertIsNone(extract.number(""))


class CategoryExtractionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.index = EvidenceIndex(marketplace="US", period=PERIOD)

    def test_market_research_fills_the_scoring_inputs(self) -> None:
        metrics = extract.extract_market_research(
            Reply("market_research"), node_id_path=NODE, period=PERIOD, index=self.index)
        self.assertAlmostEqual(metrics["avg_price"], 186.91)
        self.assertAlmostEqual(metrics["total_revenue"], 6_907_337.97)
        self.assertAlmostEqual(metrics["top5_brand_crn"], 0.3929)
        self.assertAlmostEqual(metrics["new_ratio_l12"], 0.45)
        self.assertAlmostEqual(metrics["return_ratio"], 0.015674)
        self.assertAlmostEqual(metrics["return_ratio_avg"], 0.028763)
        self.assertAlmostEqual(metrics["avg_weight"], 86.0422)

    def test_the_return_rate_arrives_with_its_sibling_benchmark(self) -> None:
        """A return rate without the category average is unreadable — 1.6% is good
        or bad only relative to what the neighbours do."""
        metrics = extract.extract_market_research(
            Reply("market_research"), node_id_path=NODE, period=PERIOD)
        self.assertLess(metrics["return_ratio"], metrics["return_ratio_avg"])

    def test_estimated_and_observed_are_split_without_being_asked(self) -> None:
        extract.extract_market_research(Reply("market_research"), node_id_path=NODE,
                                        period=PERIOD, index=self.index)
        by_metric = {r["metric"]: r for r in self.index.all_rows()}
        self.assertFalse(by_metric["total_revenue"]["observed"])
        self.assertFalse(by_metric["avg_units"]["observed"])
        self.assertTrue(by_metric["avg_price"]["observed"])
        self.assertTrue(by_metric["avg_rating"]["observed"])

    def test_a_missing_field_mints_no_evidence_and_is_recorded_as_a_gap(self) -> None:
        """An evidence row holding None would let a claim cite the absence of data."""
        class Empty(Reply):
            def __init__(self) -> None:
                super().__init__("market_research")
                self.payload = json.dumps({"data": {"items": [{"nodeIdPath": NODE}]}})

        metrics = extract.extract_market_research(Empty(), node_id_path=NODE,
                                                  period=PERIOD, index=self.index)
        self.assertEqual(metrics, {})
        self.assertEqual(len(self.index), 0)

    def test_statistics_add_the_head_listing_view(self) -> None:
        metrics = extract.extract_market_statistics(
            Reply("market_research_statistics"), node_id_path=NODE, period=PERIOD,
            index=self.index)
        self.assertAlmostEqual(metrics["hl_avg_price"], 151.11)
        self.assertAlmostEqual(metrics["hl_avg_ratings"], 788.0)
        self.assertAlmostEqual(metrics["new_product_proportion"], 0.45)

    def test_demand_trend_returns_metrics_and_a_series(self) -> None:
        metrics, series = extract.extract_demand_trend(
            Reply("market_product_demand_trend"), node_id_path=NODE, period=PERIOD,
            index=self.index)
        self.assertAlmostEqual(metrics["return_ratio"], 0.017748)
        self.assertEqual(metrics["asin_count"], 58076)
        self.assertTrue(series)
        self.assertEqual(series, sorted(series, key=lambda p: p["period"]))
        self.assertEqual(metrics["glance_views"], series[-1]["glance_views"])

    def test_price_distribution_buckets_keep_order_and_shares(self) -> None:
        buckets = extract.extract_distribution(
            Reply("market_price_distribution"), kind="price", node_id_path=NODE,
            period=PERIOD, index=self.index)
        self.assertEqual(buckets[0]["bucket_key"], "50-100")
        self.assertAlmostEqual(buckets[0]["units_ratio"], 0.2281)
        self.assertTrue(buckets[0]["evidence_id"])

    def test_brand_concentration_rows_carry_share_and_rank(self) -> None:
        brands = extract.extract_concentration(
            Reply("market_brand_concentration"), kind="brand", node_id_path=NODE,
            period=PERIOD, index=self.index)
        self.assertEqual(brands[0]["entity"], "VASAGLE")
        self.assertEqual(brands[0]["rank"], 1)
        self.assertAlmostEqual(brands[0]["revenue_ratio"], 0.0726)
        self.assertAlmostEqual(brands[0]["units_ratio"], 0.1213)

    def test_seller_type_concentration_uses_its_own_field_names(self) -> None:
        """asinNum/asinRatio rather than products/productsRatio — same shape, other spelling."""
        rows = extract.extract_concentration(
            Reply("market_seller_type_concentration"), kind="seller_type",
            node_id_path=NODE, period=PERIOD)
        fbm = next(r for r in rows if r["entity"] == "FBM")
        self.assertEqual(fbm["products"], 59)
        self.assertAlmostEqual(fbm["units_ratio"], 0.568)


class ProductExtractionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.index = EvidenceIndex(marketplace="US", period=PERIOD)
        self.products, self.metrics = extract.extract_products(
            Reply("product_research"), node_id_path=NODE, period=PERIOD, index=self.index)

    def test_one_call_fills_the_whole_competitive_set(self) -> None:
        self.assertEqual(len(self.products), len(self.metrics))
        self.assertTrue(self.products)

    def test_the_freight_profile_comes_free_with_the_product_pack(self) -> None:
        """No per-ASIN asin_detail needed for dimensions — product_research has them."""
        first = self.products[0]
        self.assertAlmostEqual(first["weight"], 75.4)
        self.assertAlmostEqual(first["pkg_weight"], 82.9)
        self.assertEqual(first["dimension"], "15.7 x 32.7 x 31.7 inches")

    def test_listing_age_is_readable(self) -> None:
        self.assertEqual(self.products[0]["available_date"], "2025-04-23")

    def test_metrics_land_in_columns(self) -> None:
        row = self.metrics[0]
        self.assertAlmostEqual(row["price"], 1019.99)
        self.assertEqual(row["units"], 1064)
        self.assertEqual(row["bsr"], 32275)
        self.assertAlmostEqual(row["rating"], 4.3)

    def test_asin_evidence_is_capped_to_the_visible_set(self) -> None:
        """Fifty ASINs times a dozen metrics is six hundred rows to read past."""
        subjects = {r["subject_id"] for r in self.index.all_rows()
                    if r["subject_kind"] == "asin"}
        self.assertLessEqual(len(subjects), 10)

    def test_asin_history_is_monthly_and_marked_estimated(self) -> None:
        history = extract.extract_asin_history(Reply("asin_prediction"), asin="B0F5WV3394")
        units = [h for h in history if h["metric"] == "units"]
        prices = [h for h in history if h["metric"] == "price"]
        self.assertTrue(units and prices)
        self.assertEqual(units[0]["period"], "202508")
        self.assertFalse(units[0]["observed"])   # the vendor models volume
        self.assertTrue(prices[0]["observed"])   # price is observed

    def test_reviews_get_a_derived_key_because_the_vendor_sends_no_id(self) -> None:
        reviews = extract.extract_reviews(Reply("review"), asin="B0F5WV3394")
        self.assertTrue(reviews)
        self.assertEqual(len({r["key"] for r in reviews}), len(reviews))
        self.assertTrue(all(r["date"].startswith("20") for r in reviews))
        self.assertTrue(all(1 <= r["star"] <= 5 for r in reviews))


class KeywordExtractionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.index = EvidenceIndex(marketplace="US", period=PERIOD)

    def test_keyword_research_rows(self) -> None:
        rows = extract.extract_keywords(Reply("keyword_research"), period=PERIOD,
                                        node_id_path=NODE, index=self.index)
        first = next(r for r in rows if r["keyword"] == "sideboard buffet cabinet")
        self.assertEqual(first["searches"], 17134)
        self.assertAlmostEqual(first["supply_demand_ratio"], 2.68)
        self.assertEqual(first["period"], "202608")   # "2026.08" normalised

    def test_keyword_miner_and_aba_share_the_extractor(self) -> None:
        miner = extract.extract_keywords(Reply("keyword_miner"), period=PERIOD)
        aba = extract.extract_keywords(Reply("aba_research_monthly"), period=PERIOD)
        self.assertTrue(miner and aba)
        self.assertTrue(any(r["spr"] is not None for r in miner))
        self.assertTrue(any(r["search_rank"] is not None for r in aba))
        self.assertTrue(all(len(r["period"]) == 6 for r in miner + aba))

    def test_keyword_evidence_covers_demand_and_competition(self) -> None:
        extract.extract_keywords(Reply("keyword_research"), period=PERIOD, index=self.index)
        metrics = {r["metric"] for r in self.index.all_rows()}
        self.assertIn("searches", metrics)
        self.assertIn("supply_demand_ratio", metrics)

    def test_traffic_edges_carry_the_natural_versus_ad_split(self) -> None:
        edges = extract.extract_keyword_edges(Reply("traffic_keyword"), asin="B0F5WV3394",
                                              period=PERIOD, index=self.index)
        self.assertTrue(edges)
        self.assertTrue(all("natural_ratio" in e for e in edges))

    def test_traffic_mix_is_computed_from_counts(self) -> None:
        """The vendor returns keyword counts per source, not percentages."""
        mix = extract.extract_traffic_mix(Reply("traffic_source"), asin="B0F5WV3394",
                                          period=PERIOD, index=self.index)
        self.assertAlmostEqual(mix["natural_proportion"], 4 / 9)
        self.assertAlmostEqual(mix["ad_proportion"], 4 / 9)
        self.assertAlmostEqual(mix["recommendation_proportion"], 1 / 9)
        self.assertAlmostEqual(
            mix["natural_proportion"] + mix["ad_proportion"]
            + mix["recommendation_proportion"], 1.0)

    def test_google_trend_collapses_weekly_points_to_months(self) -> None:
        series = extract.extract_google_trend(Reply("google_trend"), keyword="sideboard")
        self.assertTrue(series)
        self.assertTrue(all(len(p["period"]) == 6 for p in series))
        self.assertEqual([p["period"] for p in series],
                         sorted(p["period"] for p in series))


class CompletenessTests(unittest.TestCase):
    def test_a_partial_month_reports_what_is_missing(self) -> None:
        score, missing = extract.completeness(
            ["structure", "demand"], ["structure", "demand", "price", "brands"])
        self.assertAlmostEqual(score, 0.5)
        self.assertEqual(missing, ["price", "brands"])

    def test_nothing_expected_is_complete(self) -> None:
        self.assertEqual(extract.completeness([], []), (1.0, []))


if __name__ == "__main__":
    unittest.main()
