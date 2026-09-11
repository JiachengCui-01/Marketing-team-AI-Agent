"""Deterministic scoring.

The single most important test here is that a model-supplied score is overwritten:
the whole design rests on the number on screen being computed from columns, not
transcribed by a language model.
"""
from __future__ import annotations

import unittest

from server.market import scoring


def snapshot(**overrides) -> dict:
    """A healthy category-month; every test bends one dimension of it."""
    base = {
        "total_revenue": 3_000_000.0,
        "avg_price": 450.0,
        "top5_brand_crn": 0.10,
        "hl_avg_ratings": 150.0,
        "new_count_l12": 45.0,
        "new_avg_revenue_l12": 17_000.0,
        "total_revenue_for_share": None,
        "return_ratio": 0.012,
        "return_ratio_avg": 0.030,
    }
    base.update(overrides)
    return base


HISTORY_UP = [{"total_revenue": 1_000_000.0}, {"total_revenue": 1_500_000.0}]
KEYWORDS = [{"supply_demand_ratio": 80.0}, {"supply_demand_ratio": 80.0}]


class CurveTests(unittest.TestCase):
    def test_weights_sum_to_one_hundred(self) -> None:
        """An arithmetic guard against a future weight edit."""
        self.assertEqual(sum(scoring.CATEGORY_WEIGHTS.values()), 100)
        self.assertEqual(sum(scoring.PRODUCT_WEIGHTS.values()), 100)

    def test_piecewise_interpolates_and_flattens_at_the_ends(self) -> None:
        table = ((0.0, 0.0), (10.0, 100.0))
        self.assertEqual(scoring.piecewise(-5.0, table), 0.0)
        self.assertEqual(scoring.piecewise(5.0, table), 50.0)
        self.assertEqual(scoring.piecewise(999.0, table), 100.0)

    def test_a_missing_input_scores_zero_not_an_average(self) -> None:
        """Imputing would rank a category with no data above one with bad data."""
        self.assertEqual(scoring.piecewise(None, ((0.0, 0.0), (1.0, 100.0))), 0.0)

    def test_the_aov_curve_rejects_both_ends(self) -> None:
        """Freight economics, not taste: $120 cannot absorb LTL plus a return, and
        $3,000 is a showroom decision this brand does not serve."""
        cheap = scoring.score_category(snapshot(avg_price=110.0))["breakdown"]["aov_fit"]
        sweet = scoring.score_category(snapshot(avg_price=450.0))["breakdown"]["aov_fit"]
        dear = scoring.score_category(snapshot(avg_price=3_000.0))["breakdown"]["aov_fit"]
        self.assertLess(cheap, sweet)
        self.assertLess(dear, sweet)
        self.assertAlmostEqual(sweet, scoring.CATEGORY_WEIGHTS["aov_fit"], places=1)

    def test_quality_fit_is_deliberately_non_monotonic(self) -> None:
        """4.9 with forty thousand reviews is an entrenched incumbent, not an opening.
        A model asked to judge rating quality reliably gets this backwards."""
        best = scoring.score_product({"rating": 4.2})["breakdown"]["quality_fit"]
        high = scoring.score_product({"rating": 4.9})["breakdown"]["quality_fit"]
        low = scoring.score_product({"rating": 3.4})["breakdown"]["quality_fit"]
        self.assertGreater(best, high)
        self.assertGreater(best, low)


class CategoryScoreTests(unittest.TestCase):
    def test_a_strong_category_scores_near_the_ceiling(self) -> None:
        result = scoring.score_category(snapshot(), history=HISTORY_UP, keywords=KEYWORDS)
        self.assertGreaterEqual(result["score"], 90)
        self.assertEqual(result["confidence"], 1.0)
        self.assertEqual(result["missing"], [])

    def test_an_empty_snapshot_scores_zero_with_zero_confidence(self) -> None:
        result = scoring.score_category({})
        self.assertEqual(result["score"], 0)
        self.assertEqual(result["confidence"], 0.0)
        self.assertEqual(set(result["missing"]),
                         set(scoring.CATEGORY_WEIGHTS) | {scoring.RISK_KEY})

    def test_confidence_is_the_share_of_weight_actually_observed(self) -> None:
        partial = scoring.score_category({"total_revenue": 3_000_000.0, "avg_price": 450.0})
        expected = ((scoring.CATEGORY_WEIGHTS["demand_scale"]
                     + scoring.CATEGORY_WEIGHTS["aov_fit"])
                    / sum(scoring.CATEGORY_WEIGHTS.values()))
        self.assertAlmostEqual(partial["confidence"], round(expected, 2))

    def test_the_return_rate_is_read_against_its_sibling_average(self) -> None:
        """1.6% means nothing alone; 1.6% against a 2.9% neighbourhood is a strength."""
        better = scoring.score_category(snapshot(return_ratio=0.012, return_ratio_avg=0.030))
        worse = scoring.score_category(snapshot(return_ratio=0.075, return_ratio_avg=0.030))
        self.assertEqual(better["breakdown"]["return_risk"], -0.0)
        self.assertLess(worse["breakdown"]["return_risk"], -10.0)
        self.assertGreater(better["score"], worse["score"])

    def test_the_risk_penalty_is_capped(self) -> None:
        awful = scoring.score_category(snapshot(return_ratio=0.9, return_ratio_avg=0.01))
        self.assertGreaterEqual(awful["breakdown"]["return_risk"], -scoring.RISK_MAX)

    def test_concentration_is_read_as_a_wall_not_a_virtue(self) -> None:
        open_market = scoring.score_category(snapshot(top5_brand_crn=0.10))
        closed = scoring.score_category(snapshot(top5_brand_crn=0.85))
        self.assertGreater(open_market["breakdown"]["concentration"],
                           closed["breakdown"]["concentration"])

    def test_newcomer_viability_prefers_revenue_share_over_listing_count(self) -> None:
        """Ten new listings that sell nothing prove the category is open, which is
        not the same as enterable."""
        selling = snapshot(new_count_l12=45.0, new_avg_revenue_l12=17_000.0)
        not_selling = snapshot(new_count_l12=45.0, new_avg_revenue_l12=200.0)
        self.assertGreater(
            scoring.score_category(selling)["breakdown"]["new_product_viability"],
            scoring.score_category(not_selling)["breakdown"]["new_product_viability"])

    def test_newcomer_viability_falls_back_to_the_listing_ratio(self) -> None:
        fallback = {"new_ratio_l12": 0.20}
        self.assertAlmostEqual(scoring.new_revenue_share_pct(fallback), 20.0)

    def test_growth_uses_the_stored_series(self) -> None:
        flat = scoring.score_category(snapshot(), history=[{"total_revenue": 1.0},
                                                           {"total_revenue": 1.0}])
        rising = scoring.score_category(snapshot(), history=HISTORY_UP)
        self.assertGreater(rising["breakdown"]["demand_growth"],
                           flat["breakdown"]["demand_growth"])

    def test_growth_needs_two_points(self) -> None:
        self.assertIsNone(scoring.growth_pct([{"total_revenue": 1.0}]))

    def test_scoring_is_stable_across_repeated_calls(self) -> None:
        """Guards against in-place mutation of the inputs."""
        data = snapshot()
        first = scoring.score_category(data, history=HISTORY_UP, keywords=KEYWORDS)
        second = scoring.score_category(data, history=HISTORY_UP, keywords=KEYWORDS)
        self.assertEqual(first, second)


class ProductScoreTests(unittest.TestCase):
    METRICS = {"units": 5_000.0, "revenue": 500_000.0, "price": 450.0, "rating": 4.2,
               "ratings": 100.0, "bsr_cr": -60.0}
    PAIN = [{"mention_count": 71, "sample_size": 230, "fixable_in_design": True},
            {"mention_count": 48, "sample_size": 230, "fixable_in_design": True},
            {"mention_count": 25, "sample_size": 230, "fixable_in_design": False}]

    def test_a_strong_opportunity_scores_near_the_ceiling(self) -> None:
        result = scoring.score_product(
            self.METRICS, snapshot=snapshot(), history=HISTORY_UP, keywords=KEYWORDS,
            pain=self.PAIN)
        self.assertGreaterEqual(result["score"], 85)
        self.assertEqual(result["missing"], [])

    def test_pain_headroom_multiplies_negative_share_by_fixable_share(self) -> None:
        """The model names and classifies the themes; the arithmetic stays here."""
        value = scoring.pain_headroom_input(self.PAIN)
        self.assertAlmostEqual(value, (144 / 230) * (119 / 144) * 100, places=3)

    def test_pain_headroom_needs_a_sample(self) -> None:
        self.assertIsNone(scoring.pain_headroom_input([]))
        self.assertIsNone(scoring.pain_headroom_input(
            [{"mention_count": 5, "sample_size": 0}]))

    def test_an_unfixable_pain_point_is_not_headroom(self) -> None:
        fixable = scoring.pain_headroom_input(
            [{"mention_count": 50, "sample_size": 100, "fixable_in_design": True}])
        unfixable = scoring.pain_headroom_input(
            [{"mention_count": 50, "sample_size": 100, "fixable_in_design": False}])
        self.assertGreater(fixable, unfixable)

    def test_a_bare_metrics_row_still_scores_with_low_confidence(self) -> None:
        result = scoring.score_product({"price": 450.0})
        self.assertGreater(result["score"], 0)
        self.assertLess(result["confidence"], 0.3)

    def test_review_depth_discounts_an_entrenched_incumbent(self) -> None:
        shallow = scoring.score_product({"ratings": 100.0, "rating": 4.2})
        deep = scoring.score_product({"ratings": 40_000.0, "rating": 4.2})
        self.assertGreater(shallow["breakdown"]["competition"],
                           deep["breakdown"]["competition"])


class ScoreModelTests(unittest.TestCase):
    def test_the_weights_ship_with_the_response(self) -> None:
        """So the UI renders breakdown bars from the table instead of hardcoding /30."""
        model = scoring.score_model()
        self.assertEqual(model["category_weights"], scoring.CATEGORY_WEIGHTS)
        self.assertEqual(model["risk_key"], scoring.RISK_KEY)
        self.assertEqual(model["version"], "v2")

    def test_every_breakdown_key_is_in_the_weight_table(self) -> None:
        result = scoring.score_category(snapshot())
        for key in result["breakdown"]:
            self.assertIn(key, set(scoring.CATEGORY_WEIGHTS) | {scoring.RISK_KEY})


if __name__ == "__main__":
    unittest.main()
