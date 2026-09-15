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
