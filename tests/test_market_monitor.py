"""Risk and opportunity signals, and the panels that surface them.

Every signal is arithmetic over stored columns, so the whole file runs on
literals: no database, no vendor, no model. The exceptions are the panel tests
at the bottom, which need a warehouse to read from.
"""
from __future__ import annotations

import unittest

from server import db
from server.market import monitor, panels, store, taxonomy

PERIOD = "202608"
BUFFETS = "1055398:1063306:3733781:3733831"


def facts(**overrides) -> monitor.NodeFacts:
    """A healthy, unremarkable node. Each test perturbs one thing."""
    base = dict(
        node_key="n", label="Sideboards",
        snapshot={
            "total_revenue": 1_000_000.0, "avg_price": 480.0, "avg_rating": 4.5,
            "total_products": 800, "sellers": 400, "brands": 250,
            "return_ratio": 0.020, "return_ratio_avg": 0.020,
            "top5_brand_crn": 0.25, "new_ratio_l12": 0.10,
            "search_purchase_ratio": 1.0, "search_purchase_ratio_avg": 1.0,
            "hl_avg_ratings": 3000.0, "amazon_self_proportion": 0.01,
        },
        history=[
            {"period": "202605", "total_revenue": 1_000_000.0, "avg_price": 480.0,
             "return_ratio": 0.020, "top5_brand_crn": 0.25, "total_products": 800,
             "hl_avg_ratings": 3000.0, "new_ratio_l12": 0.10,
             "amazon_self_proportion": 0.01},
            {"period": "202606", "total_revenue": 1_000_000.0, "avg_price": 480.0,
             "return_ratio": 0.020, "top5_brand_crn": 0.25, "total_products": 800,
             "hl_avg_ratings": 3000.0, "new_ratio_l12": 0.10,
             "amazon_self_proportion": 0.01},
            {"period": "202607", "total_revenue": 1_000_000.0, "avg_price": 480.0,
             "return_ratio": 0.020, "top5_brand_crn": 0.25, "total_products": 800,
             "hl_avg_ratings": 3000.0, "new_ratio_l12": 0.10,
             "amazon_self_proportion": 0.01},
            {"period": PERIOD, "total_revenue": 1_000_000.0, "avg_price": 480.0,
             "return_ratio": 0.020, "top5_brand_crn": 0.25, "total_products": 800,
             "hl_avg_ratings": 3000.0, "new_ratio_l12": 0.10,
             "amazon_self_proportion": 0.01},
        ],
        peers={"revenue_growth_pct": 0.0, "total_revenue": 900_000.0},
    )
    snapshot = dict(base["snapshot"])
    snapshot.update(overrides.pop("snapshot", {}))
    base["snapshot"] = snapshot
    # Keep the last history row in step with the snapshot; a trend signal that
    # compares a snapshot against a history the snapshot is not part of is
    # measuring a fixture bug, not a market move.
    history = [dict(row) for row in base["history"]]
    history[-1].update({k: v for k, v in snapshot.items() if k in history[-1]})
    base["history"] = history
    base.update(overrides)
    return monitor.NodeFacts(**base)


def fired(alerts, signal_id: str):
    return next((a for a in alerts if a.id == signal_id), None)


class SignalTests(unittest.TestCase):
    def test_a_quiet_node_fires_nothing_alarming(self) -> None:
        alerts = monitor.scan(facts())
        self.assertEqual([a for a in alerts if a.severity == monitor.HIGH], [])

    def test_missing_inputs_fire_nothing_at_all(self) -> None:
        """An alert meaning 'we have no data' teaches people to ignore alerts."""
        empty = monitor.NodeFacts(node_key="n", snapshot={}, history=[])
        self.assertEqual(monitor.scan(empty), [])

    def test_returns_above_the_peer_average_scale_with_the_multiple(self) -> None:
        mild = fired(monitor.scan(facts(snapshot={"return_ratio": 0.023})),
                     "return_above_peers")
        bad = fired(monitor.scan(facts(snapshot={"return_ratio": 0.040})),
                    "return_above_peers")
        self.assertEqual(mild.severity, monitor.LOW)
        self.assertEqual(bad.severity, monitor.HIGH)
        self.assertEqual(bad.kind, monitor.RISK)

    def test_returns_below_the_peer_average_are_an_opportunity(self) -> None:
        """For freight furniture this is worth more than most growth."""
        alert = fired(monitor.scan(facts(snapshot={"return_ratio": 0.011})),
                      "return_below_peers")
        self.assertIsNotNone(alert)
        self.assertEqual(alert.kind, monitor.OPPORTUNITY)
        self.assertEqual(alert.extra["multiple"], 0.55)

    def test_the_two_return_signals_can_never_both_fire(self) -> None:
        for rate in (0.005, 0.02, 0.05):
            ids = {a.id for a in monitor.scan(facts(snapshot={"return_ratio": rate}))}
            self.assertLessEqual(
                len(ids & {"return_above_peers", "return_below_peers"}), 1, rate)

    def test_a_trend_needs_three_months_before_it_speaks(self) -> None:
        short = facts()
        short = monitor.NodeFacts(
            node_key="n", snapshot={**short.snapshot, "total_revenue": 500_000.0},
            history=list(short.history)[-2:], peers=short.peers)
        self.assertIsNone(fired(monitor.scan(short), "demand_falling"))

    def test_demand_falling_measures_against_a_trailing_mean(self) -> None:
        alert = fired(monitor.scan(facts(snapshot={"total_revenue": 700_000.0})),
                      "demand_falling")
        self.assertEqual(alert.severity, monitor.HIGH)
        self.assertAlmostEqual(alert.baseline, 1_000_000.0)
        self.assertAlmostEqual(alert.delta, -30.0)

    def test_growth_in_line_with_the_department_is_not_an_opportunity(self) -> None:
        """In a month when everything is up 15%, being up 15% is the weather."""
        weather = facts(snapshot={"total_revenue": 1_150_000.0},
                        peers={"revenue_growth_pct": 20.0})
        self.assertIsNone(fired(monitor.scan(weather), "demand_accelerating"))
        ahead = facts(snapshot={"total_revenue": 1_150_000.0},
                      peers={"revenue_growth_pct": 2.0})
        self.assertIsNotNone(fired(monitor.scan(ahead), "demand_accelerating"))

    def test_supply_outpacing_demand_reports_the_spread(self) -> None:
        alert = fired(monitor.scan(facts(snapshot={"total_products": 1000,
                                                   "total_revenue": 950_000.0})),
                      "supply_outpacing_demand")
        self.assertIsNotNone(alert)
        self.assertAlmostEqual(alert.delta, 30.0, places=1)
        self.assertEqual(alert.unit, "pp")

    def test_amazon_self_fires_on_level_as_well_as_on_change(self) -> None:
        alert = fired(monitor.scan(facts(snapshot={"amazon_self_proportion": 0.15})),
                      "amazon_entering")
        self.assertEqual(alert.severity, monitor.HIGH)

    def test_a_newcomer_window_behind_a_review_wall_is_demoted(self) -> None:
        open_window = fired(
            monitor.scan(facts(snapshot={"new_count_l12": 60,
                                         "new_avg_revenue_l12": 40_000.0,
                                         "new_avg_reviews_l12": 90.0})),
            "newcomer_window_open")
        walled = fired(
            monitor.scan(facts(snapshot={"new_count_l12": 60,
                                         "new_avg_revenue_l12": 40_000.0,
                                         "new_avg_reviews_l12": 4000.0})),
            "newcomer_window_open")
        self.assertEqual(open_window.severity, monitor.HIGH)
        self.assertEqual(walled.severity, monitor.MEDIUM)

    def test_a_quality_gap_needs_the_money_to_be_there_too(self) -> None:
        """A badly-rated category nobody buys from is not an opening."""
        small = facts(snapshot={"avg_rating": 3.9, "total_revenue": 100_000.0},
                      peers={"total_revenue": 900_000.0})
        self.assertIsNone(fired(monitor.scan(small), "quality_gap"))
        big = facts(snapshot={"avg_rating": 3.9}, peers={"total_revenue": 900_000.0})
        self.assertEqual(fired(monitor.scan(big), "quality_gap").severity, monitor.HIGH)

    def test_premium_headroom_picks_the_widest_band_gap(self) -> None:
        alert = fired(monitor.scan(facts(distributions={"price": [
            {"bucket_key": "$0-200", "revenue_ratio": 0.10, "products_ratio": 0.30},
            {"bucket_key": "$300-600", "revenue_ratio": 0.58, "products_ratio": 0.42},
            {"bucket_key": "$600+", "revenue_ratio": 0.32, "products_ratio": 0.28},
        ]})), "premium_headroom")
        self.assertEqual(alert.extra["band"], "$300-600")
        self.assertAlmostEqual(alert.delta, 16.0, places=1)

    def test_keyword_supply_gap_names_its_keywords(self) -> None:
        alert = fired(monitor.scan(facts(keywords=[
            {"keyword": "narrow sideboard for hallway", "searches": 6000,
             "supply_demand_ratio": 24.8},
            {"keyword": "sideboard with wine rack", "searches": 4000,
             "supply_demand_ratio": 23.9},
            {"keyword": "sideboard", "searches": 90000, "supply_demand_ratio": 0.4},
        ])), "keyword_supply_gap")
        self.assertEqual(alert.value, 2.0)
        self.assertEqual(alert.extra["top_sdr"], 24.8)
        self.assertIn("narrow sideboard for hallway", alert.extra["keywords"])

    def test_a_pain_theme_under_twenty_reviews_is_not_a_theme(self) -> None:
        thin = facts(themes=[{"theme": "damage", "theme_label": "运输磕碰",
                              "fixable_in_design": True, "share_of_negative": 0.4,
                              "sample_size": 12}])
        self.assertIsNone(fired(monitor.scan(thin), "pain_concentrated"))
        solid = facts(themes=[{"theme": "damage", "theme_label": "运输磕碰",
                               "fixable_in_design": True, "share_of_negative": 0.31,
                               "sample_size": 64}])
        alert = fired(monitor.scan(solid), "pain_concentrated")
        self.assertEqual(alert.severity, monitor.HIGH)
        self.assertEqual(alert.extra["sample_size"], 64)

    def test_traffic_mix_reads_both_ways_but_only_one_fires(self) -> None:
        paid = monitor.scan(facts(products=[{"ad_proportion": 0.6, "natural_proportion": 0.3},
                                            {"ad_proportion": 0.56, "natural_proportion": 0.34}]))
        self.assertIsNotNone(fired(paid, "ad_dependence"))
        self.assertIsNone(fired(paid, "organic_winnable"))
        organic = monitor.scan(facts(products=[{"ad_proportion": 0.2, "natural_proportion": 0.7}]))
        self.assertIsNotNone(fired(organic, "organic_winnable"))

    def test_offamazon_only_leads_when_amazon_is_not_already_ahead(self) -> None:
        series = [{"google_trend_index": v} for v in (50, 52, 48, 70, 74, 78)]
        leading = facts(trend_index=series)
        self.assertIsNotNone(fired(monitor.scan(leading), "offamazon_leading"))
        both = facts(snapshot={"total_revenue": 2_000_000.0}, trend_index=series)
        self.assertIsNone(fired(monitor.scan(both), "offamazon_leading"))

    def test_alerts_come_back_most_severe_first(self) -> None:
        alerts = monitor.scan(facts(snapshot={
            "return_ratio": 0.05, "total_revenue": 700_000.0, "avg_price": 450.0}))
        ranks = [monitor._SEVERITY_RANK[a.severity] for a in alerts]
        self.assertEqual(ranks, sorted(ranks, reverse=True))

    def test_scanning_is_deterministic(self) -> None:
        sample = facts(snapshot={"return_ratio": 0.05, "total_revenue": 700_000.0})
        first = [(a.id, a.severity, round(a.magnitude, 6)) for a in monitor.scan(sample)]
        second = [(a.id, a.severity, round(a.magnitude, 6)) for a in monitor.scan(sample)]
        self.assertEqual(first, second)


class ProductSignalTests(unittest.TestCase):
    """The design-facing family: what the thing we would build has to be.

    These read the same warehouse as everything else — ``avg_weight`` and
    ``avg_volume`` from the category call, ``variations`` from the product call,
    the classifier's ``fixable_in_design`` flag on each review theme — so they
    run on literals like the rest of the file.
    """

    def themes(self, *specs) -> list[dict]:
        """(category, share, fixable, sample) tuples into theme rows."""
        return [{"theme": f"t{i}", "theme_label": f"theme {i}", "category": category,
                 "fixable_in_design": fixable, "return_driving": False,
                 "share_of_negative": share, "sample_size": sample,
                 "mention_count": int(share * sample)}
                for i, (category, share, fixable, sample) in enumerate(specs)]

    # ---- physical envelope -------------------------------------------------

    def test_weight_escalates_through_the_freight_tiers(self) -> None:
        light = fired(monitor.scan(facts(snapshot={"avg_weight": 60.0})), "freight_heavy")
        heavy = fired(monitor.scan(facts(snapshot={"avg_weight": 180.0})), "freight_heavy")
        self.assertEqual(light.severity, monitor.LOW)
        self.assertEqual(heavy.severity, monitor.HIGH)
        self.assertEqual(heavy.kind, monitor.RISK)
        self.assertEqual(heavy.unit, "lb")

    def test_a_parcel_weight_category_says_nothing_about_freight(self) -> None:
        self.assertIsNone(
            fired(monitor.scan(facts(snapshot={"avg_weight": 22.0})), "freight_heavy"))

    def test_weight_carries_the_department_median_as_its_baseline(self) -> None:
        alert = fired(monitor.scan(facts(snapshot={"avg_weight": 120.0},
                                         peers={"avg_weight": 70.0})), "freight_heavy")
        self.assertEqual(alert.baseline, 70.0)

    def test_variation_depth_is_a_median_not_a_maximum(self) -> None:
        """One ten-variant listing must not make the shelf look like a range."""
        outlier = facts(products=[{"variations": 10}, {"variations": 1},
                                  {"variations": 1}, {"variations": 1}])
        self.assertIsNone(fired(monitor.scan(outlier), "variation_depth_expected"))
        real = facts(products=[{"variations": 6}, {"variations": 7},
                               {"variations": 5}, {"variations": 8}])
        alert = fired(monitor.scan(real), "variation_depth_expected")
        self.assertEqual(alert.severity, monitor.HIGH)
        self.assertEqual(alert.extra["asins"], 4)

    # ---- what the complaints are made of -----------------------------------

    def test_design_fixable_share_sums_only_the_fixable_themes(self) -> None:
        alert = fired(monitor.scan(facts(themes=self.themes(
            ("assembly_difficulty", 0.30, True, 60),
            ("material_quality", 0.20, True, 60),
            ("customer_service", 0.40, False, 60),
        ))), "design_fixable_share")
        self.assertEqual(alert.kind, monitor.OPPORTUNITY)
        self.assertAlmostEqual(alert.value, 50.0)
        self.assertEqual(alert.severity, monitor.MEDIUM)

    def test_a_category_whose_complaints_are_service_problems_stays_quiet(self) -> None:
        """Couriers and call centres are somebody else's brief."""
        self.assertIsNone(fired(monitor.scan(facts(themes=self.themes(
            ("customer_service", 0.55, False, 80),
            ("instructions", 0.05, False, 80),
        ))), "design_fixable_share"))

    def test_assembly_and_missing_parts_are_counted_together(self) -> None:
        alert = fired(monitor.scan(facts(themes=self.themes(
            ("assembly_difficulty", 0.14, True, 70),
            ("missing_or_wrong_parts", 0.09, True, 70),
            ("finish_color", 0.30, True, 70),
        ))), "assembly_burden")
        self.assertAlmostEqual(alert.value, 23.0)
        self.assertEqual(alert.severity, monitor.MEDIUM)
        self.assertEqual(len(alert.extra["themes"]), 2)

    def test_transit_damage_is_a_risk_and_quotes_the_shelf_weight(self) -> None:
        alert = fired(monitor.scan(facts(
            snapshot={"avg_weight": 140.0},
            themes=self.themes(("damage_in_transit", 0.22, True, 55)),
        )), "transit_damage_load")
        self.assertEqual(alert.kind, monitor.RISK)
        self.assertEqual(alert.severity, monitor.HIGH)
        self.assertIn("140", str(alert.extra["weight"]))

    def test_a_thin_review_sample_fires_nothing(self) -> None:
        """Under twenty negatives a theme is three people with one problem."""
        thin = facts(themes=self.themes(("assembly_difficulty", 0.90, True, 8)))
        ids = {a.id for a in monitor.scan(thin)}
        self.assertEqual(
            ids & {"design_fixable_share", "assembly_burden", "transit_damage_load"},
            set())

    # ---- the family as a whole ---------------------------------------------

    def test_the_product_family_is_reachable_from_a_full_node(self) -> None:
        rich = facts(
            snapshot={"avg_weight": 112.0, "avg_volume": 41_000.0},
            products=[{"variations": 5}, {"variations": 4}, {"variations": 6}],
            themes=self.themes(("assembly_difficulty", 0.21, True, 64),
                               ("damage_in_transit", 0.19, True, 64),
                               ("missing_or_wrong_parts", 0.11, True, 64)),
        )
        family = {a.id for a in monitor.scan(rich) if a.family == "product"}
        self.assertEqual(family, {"freight_heavy", "variation_depth_expected",
                                  "design_fixable_share", "assembly_burden",
                                  "transit_damage_load"})

    def test_every_product_signal_has_both_translations(self) -> None:
        """A template gap degrades to a bare id on screen, which reads as a bug."""
        for signal_id in ("freight_heavy", "variation_depth_expected",
                          "design_fixable_share", "assembly_burden",
                          "transit_damage_load"):
            with self.subTest(signal_id):
                self.assertIn("zh", monitor._TEXT[signal_id])
                self.assertIn("en", monitor._TEXT[signal_id])

    def test_the_templates_render_with_real_fields(self) -> None:
        """describe() swallows a KeyError into a bare title; catch it here instead."""
        rich = facts(
            snapshot={"avg_weight": 112.0, "avg_volume": 41_000.0},
            products=[{"variations": 5}, {"variations": 4}, {"variations": 6}],
            themes=self.themes(("assembly_difficulty", 0.21, True, 64),
                               ("damage_in_transit", 0.19, True, 64)),
        )
        for alert in monitor.scan(rich):
            if alert.family != "product":
                continue
            for language in ("zh", "en"):
                with self.subTest(alert.id, language=language):
                    title, detail = monitor.describe(alert, language)
                    self.assertNotEqual(title, alert.id)
                    self.assertTrue(detail, "empty detail means a template field is missing")


class DescribeTests(unittest.TestCase):
    def test_every_signal_has_both_translations(self) -> None:
        for signal in monitor.SIGNALS:
            with self.subTest(signal=signal.__name__):
                entry = monitor._TEXT.get(signal.__name__)
                self.assertIsNotNone(entry)
                self.assertIn("zh", entry)
                self.assertIn("en", entry)

    def test_a_negative_change_does_not_print_a_double_sign(self) -> None:
        alert = fired(monitor.scan(facts(snapshot={"total_products": 1000,
                                                   "total_revenue": 800_000.0})),
                      "supply_outpacing_demand")
        for language in ("zh", "en"):
            _title, detail = monitor.describe(alert, language)
            self.assertNotIn("+-", detail)
            self.assertIn("-20", detail)

    def test_a_template_is_never_left_with_raw_placeholders(self) -> None:
        for signal in monitor.SIGNALS:
            alert = monitor.Alert(id=signal.__name__, kind=monitor.RISK, family="x",
                                  severity=monitor.LOW, magnitude=1.0, metric="m")
            for language in ("zh", "en"):
                title, detail = monitor.describe(alert, language)
                self.assertNotIn("{", title, signal.__name__)
                self.assertNotIn("{", detail, signal.__name__)

    def test_the_model_brief_lists_both_sides_even_when_empty(self) -> None:
        bundle = monitor.split([])
        for language in ("zh", "en"):
            text = monitor.brief(bundle, language)
            self.assertIn("(none)" if language == "en" else "（无）", text)

    def test_the_brief_forbids_inventing_a_risk(self) -> None:
        text = monitor.brief(monitor.split([]), "en")
        self.assertIn("do not add risks that are not listed", text)


class DiversityTests(unittest.TestCase):
    """A department-wide move must not fill the board with one sentence."""

    @staticmethod
    def alerts(signal_id: str, count: int, severity: str = monitor.HIGH,
               magnitude: float = 90.0) -> list[dict]:
        return [{"id": signal_id, "key": f"n{i}|{signal_id}", "kind": monitor.RISK,
                 "severity": severity, "magnitude": magnitude - i}
                for i in range(count)]

    def test_one_signal_cannot_occupy_the_whole_board(self) -> None:
        everywhere = self.alerts("amazon_entering", 12)
        rare = self.alerts("return_above_peers", 2, magnitude=40.0)
        head = monitor.diversify(everywhere + rare)[:5]
        self.assertEqual(len([a for a in head if a["id"] == "amazon_entering"]),
                         monitor.MAX_PER_SIGNAL)
        self.assertIn("return_above_peers", {a["id"] for a in head})

    def test_the_repeats_are_demoted_not_dropped(self) -> None:
        alerts = self.alerts("amazon_entering", 12)
        self.assertEqual(len(monitor.diversify(alerts)), 12)

    def test_the_worst_thing_is_still_first(self) -> None:
        """Diversity reorders the tail, never the headline."""
        common = self.alerts("amazon_entering", 6, magnitude=95.0)
        self.assertEqual(monitor.diversify(common)[0]["magnitude"], 95.0)
        louder = self.alerts("demand_falling", 1, magnitude=99.0)
        self.assertEqual(monitor.diversify(common + louder)[0]["id"], "demand_falling")
        quieter = self.alerts("demand_falling", 1, magnitude=10.0)
        self.assertEqual(monitor.diversify(common + quieter)[0]["id"], "amazon_entering")

    def test_severity_still_outranks_diversity(self) -> None:
        """Three high-severity repeats beat a low-severity novelty."""
        high = self.alerts("amazon_entering", 3, magnitude=90.0)
        low = self.alerts("price_erosion", 1, severity=monitor.LOW, magnitude=99.0)
        order = [a["id"] for a in monitor.diversify(high + low)]
        self.assertEqual(order[:3], ["amazon_entering"] * 3)
        self.assertEqual(order[3], "price_erosion")

    def test_a_demoted_repeat_never_falls_below_a_lesser_severity(self) -> None:
        """The whole point of a risk panel is that worse things come first."""
        high = self.alerts("amazon_entering", 9, magnitude=90.0)
        low = self.alerts("ad_dependence", 3, severity=monitor.LOW, magnitude=99.0)
        severities = [a["severity"] for a in monitor.diversify(high + low)]
        self.assertEqual(severities, [monitor.HIGH] * 9 + [monitor.LOW] * 3)

    def test_diversity_applies_within_each_tier(self) -> None:
        mixed = (self.alerts("amazon_entering", 5, magnitude=90.0)
                 + self.alerts("demand_falling", 2, magnitude=80.0)
                 + self.alerts("price_erosion", 5, severity=monitor.LOW, magnitude=70.0)
                 + self.alerts("return_rising", 2, severity=monitor.LOW, magnitude=60.0))
        order = [a["id"] for a in monitor.diversify(mixed)]
        self.assertEqual(order[:5], ["amazon_entering"] * 3 + ["demand_falling"] * 2)
        self.assertEqual(order[7:12], ["price_erosion"] * 3 + ["return_rising"] * 2)


class PeerMedianTests(unittest.TestCase):
    def test_growth_medians_ignore_nodes_without_enough_history(self) -> None:
        medians = monitor.peer_medians(
            [{"total_revenue": 100.0}, {"total_revenue": 300.0}],
            {"a": [{"total_revenue": 100.0}],  # one month: no growth to compute
             "b": [{"total_revenue": 100.0}, {"total_revenue": 100.0},
                   {"total_revenue": 100.0}, {"total_revenue": 150.0}]},
        )
        self.assertAlmostEqual(medians["revenue_growth_pct"], 50.0)
        self.assertAlmostEqual(medians["total_revenue"], 200.0)

    def test_no_usable_history_yields_none_rather_than_zero(self) -> None:
        """Zero would read as 'the department is flat', which is a claim."""
        medians = monitor.peer_medians([], {})
        self.assertIsNone(medians["revenue_growth_pct"])
        self.assertIsNone(medians["total_revenue"])


class PanelTests(unittest.TestCase):
    """The deterministic builders, against a warehouse with two months in it."""

    def setUp(self) -> None:
        db.reset_for_tests()
        taxonomy.ensure_nodes()
        for period, revenue, price in (("202607", 1_000_000.0, 500.0),
                                       (PERIOD, 700_000.0, 460.0)):
            store.upsert_node_snapshot("US", BUFFETS, period, {
                "total_revenue": revenue, "avg_price": price, "avg_rating": 4.05,
                "total_products": 800, "sellers": 400, "brands": 250,
                "return_ratio": 0.031, "return_ratio_avg": 0.019,
                "top5_brand_crn": 0.26, "top10_brand_crn": 0.41,
                "fba_proportion": 0.72, "fbm_proportion": 0.2,
                "amazon_self_proportion": 0.02, "ebc_proportion": 0.55,
                "search_purchase_ratio": 0.8, "search_purchase_ratio_avg": 1.1,
                "glance_views": 900_000.0, "hl_avg_ratings": 6310.0,
                "new_count_l12": 40, "new_avg_revenue_l12": 30_000.0,
                "new_ratio_l12": 0.16,
            })
        store.replace_distribution("US", BUFFETS, PERIOD, "price", [
            {"bucket_key": "$0-200", "revenue_ratio": 0.10, "products_ratio": 0.30,
             "products": 240, "revenue": 70_000.0},
            {"bucket_key": "$300-600", "revenue_ratio": 0.58, "products_ratio": 0.46,
             "products": 368, "revenue": 406_000.0},
        ])
        store.replace_distribution("US", BUFFETS, PERIOD, "rating", [
            {"bucket_key": "4.0-4.5", "products_ratio": 0.4, "products": 320},
            {"bucket_key": "4.5-5.0", "products_ratio": 0.6, "products": 480},
        ])
        store.replace_concentration("US", BUFFETS, PERIOD, "brand", [
            {"entity": "Acme", "rank": 1, "revenue_ratio": 0.09},
        ])
        store.replace_concentration("US", BUFFETS, PERIOD, "seller_type", [
            {"entity": "FBA", "rank": 1, "revenue_ratio": 0.72},
        ])

    def test_the_rollup_states_its_coverage_rather_than_implying_totality(self) -> None:
        """The vendor's own total covers ~100 head listings; a label that reads
        as market-wide is the mistake, not the number."""
        store.upsert_node_snapshot("US", BUFFETS, PERIOD, {"product_pool": 13781})
        store.upsert_product_metrics([
            {"marketplace": "US", "asin": f"B{i:04d}", "node_id_path": BUFFETS,
             "period": PERIOD, "revenue": 100_000.0, "units": 400}
            for i in range(150)])
        board = panels.build_overview("US", PERIOD, "zh")
        stats = board["coverage_stats"]
        self.assertEqual(stats["asins"], 150)
        self.assertEqual(stats["pool"], 13781)
        self.assertEqual(stats["revenue"], 15_000_000.0)
        coverage = next(k for k in board["headline"]["kpis"] if "覆盖" in k["label"])
        self.assertEqual(coverage["value"], "150 / 13,781")
        self.assertFalse(coverage["estimated"])   # a count is observed, not modelled

    def test_money_stays_flagged_as_a_vendor_model_even_for_a_closed_month(self) -> None:
        """SellerSprite infers every money figure from BSR; Amazon publishes
        category revenue to nobody. A finished month does not change that."""
        store.upsert_product_metrics([
            {"marketplace": "US", "asin": "B1", "node_id_path": BUFFETS,
             "period": PERIOD, "revenue": 100.0}])
        board = panels.build_overview("US", PERIOD, "zh")
        revenue = board["headline"]["kpis"][0]
        self.assertTrue(revenue["estimated"])

    def test_a_node_with_no_asin_rows_falls_back_to_the_vendor_total(self) -> None:
        board = panels.build_overview("US", PERIOD, "zh")
        revenue = board["headline"]["kpis"][0]
        self.assertNotEqual(revenue["value"], "—")
        self.assertIn("头部", revenue["hint"])

    def test_a_kpi_with_nothing_behind_it_is_not_shipped(self) -> None:
        """Including the composite ones — "— / — / —" slips an equality check."""
        db.reset_for_tests()
        taxonomy.ensure_nodes()
        store.upsert_node_snapshot("US", BUFFETS, PERIOD, {"avg_price": 186.91})
        header = panels.build_category("US", BUFFETS, PERIOD, "zh")["header"]
        values = [k["value"] for k in header["kpis"]]
        self.assertNotIn("—", values)
        self.assertFalse([v for v in values
                          if not v.replace("—", "").replace("/", "").strip()])
        self.assertIn("$187", values)          # the one that did arrive survives

    def test_a_partly_filled_composite_kpi_is_kept(self) -> None:
        """Two thirds of an answer is still an answer."""
        db.reset_for_tests()
        taxonomy.ensure_nodes()
        store.upsert_node_snapshot("US", BUFFETS, PERIOD,
                                   {"total_products": 1816, "brands": 59})
        header = panels.build_category("US", BUFFETS, PERIOD, "zh")["header"]
        self.assertIn("1816 / — / 59", [k["value"] for k in header["kpis"]])

    def test_the_board_carries_the_monitor_and_the_coverage_panel(self) -> None:
        board = panels.build_overview("US", PERIOD, "zh")
        self.assertTrue(board["board"])
        self.assertIn("risks", board["monitor"])
        self.assertTrue(board["coverage"]["families"])
        self.assertGreater(board["coverage"]["present"], 0)

    def test_the_board_surfaces_the_families_it_actually_holds(self) -> None:
        present = {f["key"] for f in panels.build_overview("US", PERIOD, "zh")["coverage"]
                   ["families"] if f["present"]}
        self.assertIn("distribution_price", present)
        self.assertIn("distribution_rating", present)
        self.assertIn("concentration_brand", present)
        self.assertNotIn("review", present)

    def test_the_board_renders_the_structural_sections(self) -> None:
        board = panels.build_overview("US", PERIOD, "zh")
        for key in ("treemap", "trend", "supply", "fulfilment", "quality",
                    "conversion", "newproduct", "concentration"):
            with self.subTest(section=key):
                self.assertTrue(board[key], key)

    def test_revenue_per_listing_is_computed_not_guessed(self) -> None:
        row = panels.build_overview("US", PERIOD, "zh")["supply"][0]
        self.assertAlmostEqual(row["revenue_per_listing"], 700_000.0 / 800)

    def test_the_deep_dive_renders_the_rotating_distributions(self) -> None:
        detail = panels.build_category("US", BUFFETS, PERIOD, "zh")
        kinds = {panel["kind"] for panel in detail["distributions"]}
        self.assertIn("rating", kinds)
        # price and listing_date already have their own section
        self.assertNotIn("price", kinds)
        self.assertEqual({p["kind"] for p in detail["concentration"]}, {"seller_type"})

    def test_the_benchmark_inverts_the_axes_where_lower_is_better(self) -> None:
        detail = panels.build_category("US", BUFFETS, PERIOD, "zh")
        axes = {axis["key"]: axis for axis in detail["benchmark"]}
        # Sole node, so it *is* the median: every axis sits at parity, and the
        # inverted ones have to land at parity too rather than at the top.
        for axis in axes.values():
            self.assertAlmostEqual(axis["score"], 50.0, delta=0.1, msg=axis["key"])

    def test_the_deep_dive_monitor_is_scoped_to_its_own_node(self) -> None:
        detail = panels.build_category("US", BUFFETS, PERIOD, "zh")
        for alert in detail["monitor"]["risks"] + detail["monitor"]["opportunities"]:
            self.assertEqual(alert["node_key"], BUFFETS)

    def test_returns_well_above_the_peer_average_reach_the_board(self) -> None:
        board = panels.build_overview("US", PERIOD, "zh")
        ids = {a["id"] for a in board["monitor"]["risks"]}
        self.assertIn("return_above_peers", ids)

    def test_english_and_chinese_render_different_prose_for_one_alert(self) -> None:
        zh = panels.build_overview("US", PERIOD, "zh")["monitor"]["risks"]
        en = panels.build_overview("US", PERIOD, "en")["monitor"]["risks"]
        self.assertEqual({a["id"] for a in zh}, {a["id"] for a in en})
        self.assertNotEqual(zh[0]["title"], en[0]["title"])


if __name__ == "__main__":
    unittest.main()
