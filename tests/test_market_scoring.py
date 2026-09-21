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

    def test_the_fallback_curve_still_rejects_both_ends(self) -> None:
        """With no distribution collected the shipped curve is all there is, and a
        board that scored every category zero on price would rank on noise."""
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


class PriceModelTests(unittest.TestCase):
    """Price fit is read off the department's own revenue distribution.

    It used to be a constant curve peaking around $300-900. That asserted two
    different things at once — where this business can make money, and where the
    market takes its money — and only the first of those is ours to declare.
    """

    def listings(self, spec: list[tuple[float, float]]) -> list[dict]:
        """(price, revenue) pairs, repeated enough to clear the binning floor."""
        out = []
        while len(out) < scoring.MIN_PRICE_ROWS:
            out += [{"price": price, "revenue": revenue} for price, revenue in spec]
        return out

    def test_the_peak_follows_the_money_not_a_constant(self) -> None:
        cheap_market = self.listings([(80.0, 900_000.0), (400.0, 20_000.0)])
        curve = scoring.price_model_from_listings(cheap_market)
        self.assertGreater(scoring.piecewise(80.0, curve),
                           scoring.piecewise(400.0, curve))

    def test_the_same_price_scores_differently_in_two_departments(self) -> None:
        """Which is the whole point: $400 is premium in one shelf and mid in another."""
        budget = scoring.price_model_from_listings(
            self.listings([(90.0, 800_000.0), (400.0, 40_000.0)]))
        premium = scoring.price_model_from_listings(
            self.listings([(90.0, 40_000.0), (400.0, 800_000.0)]))
        self.assertLess(scoring.piecewise(400.0, budget),
                        scoring.piecewise(400.0, premium))

    def test_bins_hold_equal_counts_so_bucket_width_cannot_skew_it(self) -> None:
        spec = [(float(p), 1_000.0) for p in range(50, 450, 10)]
        curve = scoring.price_model_from_listings(
            [{"price": p, "revenue": r} for p, r in spec])
        values = [value for _price, value in curve]
        # Revenue is flat across the range, so every bin reads the same.
        self.assertAlmostEqual(min(values), max(values), places=0)

    def test_too_few_priced_listings_is_none_not_a_curve_from_nine_rows(self) -> None:
        self.assertIsNone(scoring.price_model_from_listings(
            [{"price": 100.0, "revenue": 1.0}] * 9))

    def test_listings_without_a_price_or_revenue_are_skipped(self) -> None:
        rows = self.listings([(200.0, 10_000.0)])
        rows += [{"price": None, "revenue": 99_000_000.0},
                 {"price": 500.0, "revenue": None}]
        curve = scoring.price_model_from_listings(rows)
        self.assertTrue(all(price > 0 for price, _v in curve))

    # ---- the vendor's bands, for when listings are thin --------------------

    def test_band_labels_are_parsed_including_the_open_top(self) -> None:
        self.assertEqual(scoring.band_bounds("150-200"), (150.0, 200.0))
        self.assertEqual(scoring.band_bounds("$1,000+"), (1000.0, 2000.0))
        self.assertIsNone(scoring.band_bounds("unknown"))

    def test_the_open_bands_are_read_in_either_locale(self) -> None:
        """The vendor writes the open bins in the locale of the call, and the
        top one holds the premium revenue — dropping it is not an option."""
        self.assertEqual(scoring.band_bounds("800以上"), (800.0, 1600.0))
        self.assertEqual(scoring.band_bounds("1000及以上"), (1000.0, 2000.0))
        self.assertEqual(scoring.band_bounds("over 300"), (300.0, 600.0))

    def test_an_open_bottom_band_is_the_band_below_its_number(self) -> None:
        """"<100" ends in digits, so the open-top pattern used to match it and
        answer with (100, 200) — the band on the wrong side of the number."""
        self.assertEqual(scoring.band_bounds("<100"), (0.0, 100.0))
        self.assertEqual(scoring.band_bounds("50以下"), (0.0, 50.0))
        self.assertEqual(scoring.band_bounds("under 25"), (0.0, 25.0))

    def test_the_band_curve_peaks_on_the_fattest_band(self) -> None:
        curve = scoring.price_model([
            {"bucket_key": "50-100", "revenue": 100_000.0},
            {"bucket_key": "100-150", "revenue": 200_000.0},
            {"bucket_key": "150-200", "revenue": 900_000.0},
        ])
        self.assertEqual(scoring.piecewise(175.0, curve), 100.0)
        self.assertLess(scoring.piecewise(75.0, curve), 50.0)

    def test_no_usable_bands_falls_back_rather_than_zeroing_the_factor(self) -> None:
        """A factor that scores zero for everyone silently deletes its own weight."""
        curve = scoring.price_model([{"bucket_key": "unknown", "revenue": 5.0}])
        self.assertGreater(scoring.piecewise(450.0, curve), 0.0)

    def test_the_ui_is_shown_nothing_while_the_fallback_is_in_use(self) -> None:
        """Presenting a shipped constant as a reading is the thing to avoid."""
        self.assertEqual(scoring.price_curve_rows(scoring.price_model([])), [])
        real = scoring.price_model([{"bucket_key": "50-100", "revenue": 10.0},
                                    {"bucket_key": "100-150", "revenue": 20.0}])
        self.assertEqual(len(scoring.price_curve_rows(real)), 2)

    def test_a_supplied_curve_reaches_both_scorers(self) -> None:
        curve = ((100.0, 100.0), (1_000.0, 0.0))
        category = scoring.score_category(snapshot(avg_price=100.0), aov_curve=curve)
        product = scoring.score_product({"price": 100.0}, aov_curve=curve)
        self.assertAlmostEqual(category["breakdown"]["aov_fit"],
                               scoring.CATEGORY_WEIGHTS["aov_fit"], places=1)
        self.assertAlmostEqual(product["breakdown"]["aov_fit"],
                               scoring.PRODUCT_WEIGHTS["aov_fit"], places=1)


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
        self.assertEqual(model["version"], f"v{scoring.FORMULA_VERSION}")

    def test_every_breakdown_key_is_in_the_weight_table(self) -> None:
        result = scoring.score_category(snapshot())
        for key in result["breakdown"]:
            self.assertIn(key, set(scoring.CATEGORY_WEIGHTS) | {scoring.RISK_KEY})


if __name__ == "__main__":
    unittest.main()
