"""Evidence ids, the model-facing sheet, and citation enforcement.

These are the tests that make "every AI conclusion is traceable" a property of the
code rather than a sentence in a prompt.
"""
from __future__ import annotations

import unittest

from server.market import evidence


def index_with(*facts: tuple[str, str, float]) -> evidence.EvidenceIndex:
    index = evidence.EvidenceIndex(marketplace="US", period="202608")
    for subject, metric, value in facts:
        index.mint(subject_kind="node", subject_id=subject, metric=metric, value=value,
                   tool="market_research", field_path=f"$.{metric}", unit="USD")
    return index


class IdentityTests(unittest.TestCase):
    def test_ids_are_stable_across_runs(self) -> None:
        """Hashing the call id would mint a fresh id for the same fact every month."""
        args = dict(marketplace="US", subject_kind="node", subject_id="1:2",
                    metric="avg_price", period="202608", tool="market_research")
        self.assertEqual(evidence.mint_id(**args), evidence.mint_id(**args))

    def test_a_different_period_is_a_different_fact(self) -> None:
        base = dict(marketplace="US", subject_kind="node", subject_id="1:2",
                    metric="avg_price", tool="market_research")
        self.assertNotEqual(evidence.mint_id(**base, period="202607"),
                            evidence.mint_id(**base, period="202608"))

    def test_minting_the_same_fact_twice_keeps_one_row(self) -> None:
        index = index_with(("1:2", "avg_price", 512.0))
        index.mint(subject_kind="node", subject_id="1:2", metric="avg_price",
                   value=518.0, tool="market_research")
        self.assertEqual(len(index), 1)
        self.assertAlmostEqual(index.all_rows()[0]["value_num"], 518.0)

    def test_a_missing_value_mints_nothing_and_notes_a_gap(self) -> None:
        index = evidence.EvidenceIndex()
        self.assertIsNone(index.mint(subject_kind="node", subject_id="1:2",
                                     metric="return_ratio", value=None,
                                     tool="market_research"))
        self.assertEqual(len(index), 0)
        self.assertIn("1:2:return_ratio", index.gaps)


class QualityTests(unittest.TestCase):
    def test_estimated_metrics_are_recognised_without_being_told(self) -> None:
        self.assertTrue(evidence.is_estimated("revenue"))
        self.assertTrue(evidence.is_estimated("total_units"))
        self.assertFalse(evidence.is_estimated("price"))
        self.assertFalse(evidence.is_estimated("rating"))

    def test_a_thin_sample_is_labelled(self) -> None:
        self.assertEqual(evidence.assess(metric="avg_price", sample_size=17),
                         "small_sample")
        self.assertEqual(evidence.assess(metric="avg_price", sample_size=400), "ok")

    def test_review_themes_have_their_own_sample_floor(self) -> None:
        self.assertEqual(evidence.assess(metric="review_theme_share", sample_size=25), "ok")
        self.assertEqual(evidence.assess(metric="avg_price", sample_size=25), "small_sample")

    def test_two_months_behind_is_stale_one_is_not(self) -> None:
        """Mid-month the previous month is the freshest complete data there is."""
        self.assertEqual(evidence.assess(metric="avg_price", period="202607",
                                         current_period="202608"), "ok")
        self.assertEqual(evidence.assess(metric="avg_price", period="202606",
                                         current_period="202608"), "stale")

    def test_an_outlier_is_flagged_against_its_siblings(self) -> None:
        siblings = [100.0, 110.0, 120.0, 130.0, 140.0, 150.0]
        self.assertEqual(evidence.assess(metric="avg_price", value=9000.0,
                                         siblings=siblings), "outlier")
        self.assertEqual(evidence.assess(metric="avg_price", value=125.0,
                                         siblings=siblings), "ok")


class SheetTests(unittest.TestCase):
    def test_the_sheet_marks_estimates(self) -> None:
        index = evidence.EvidenceIndex(period="202608")
        index.mint(subject_kind="node", subject_id="1:2", metric="total_revenue",
                   value=6_907_337.97, tool="market_research", unit="USD")
        index.mint(subject_kind="node", subject_id="1:2", metric="avg_price",
                   value=186.91, tool="market_research", unit="USD")
        sheet = index.sheet(language="en")
        revenue_line = next(l for l in sheet.splitlines() if "total_revenue" in l)
        price_line = next(l for l in sheet.splitlines() if "avg_price" in l)
        self.assertIn("ESTIMATE", revenue_line)
        self.assertIn("observed", price_line)

    def test_the_sheet_states_its_gaps(self) -> None:
        index = evidence.EvidenceIndex(period="202608")
        index.note_gap("1:2:return_ratio")
        self.assertIn("return_ratio", index.sheet(language="en"))
        self.assertIn("GAPS", index.sheet(language="en"))

    def test_the_sheet_carries_the_sample_size(self) -> None:
        index = evidence.EvidenceIndex(period="202608")
        index.mint(subject_kind="node", subject_id="1:2", metric="avg_price", value=1.0,
                   tool="market_research", sample_size=17)
        self.assertIn("n=17", index.sheet(language="en"))

    def test_rebuilding_an_index_from_stored_rows(self) -> None:
        original = index_with(("1:2", "avg_price", 512.0))
        rebuilt = evidence.index_from_rows(original.all_rows())
        self.assertEqual(rebuilt.ids(), original.ids())


class CitationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.index = index_with(("1:2", "avg_price", 512.0), ("1:2", "total_revenue", 1.0))
        self.allowed = self.index.ids()
        self.known = sorted(self.allowed)[0]

    def test_a_claim_with_no_valid_citation_is_dropped(self) -> None:
        payload = {"recommendations": [
            {"title": "kept", "evidence_ids": [self.known]},
            {"title": "dropped", "evidence_ids": ["ev_deadbeef1234"]},
            {"title": "also dropped", "evidence_ids": []},
        ]}
        cleaned, dropped = evidence.validate_citations(payload, self.allowed)
        self.assertEqual([r["title"] for r in cleaned["recommendations"]], ["kept"])
        self.assertEqual(len(dropped), 2)

    def test_an_unknown_id_inside_a_valid_claim_is_pruned(self) -> None:
        payload = {"claim": {"text": "ok", "evidence_ids": [self.known, "ev_nope00000000"]}}
        cleaned, _ = evidence.validate_citations(payload, self.allowed)
        self.assertEqual(cleaned["claim"]["evidence_ids"], [self.known])

    def test_a_sentence_with_a_number_and_no_citation_is_removed(self) -> None:
        """Digits are the failure mode that matters: an unsourced adjective is
        noise, an unsourced number is a lie."""
        text = (f"类目均价为 512 美元 [{self.known}](evidence:{self.known})。"
                f"退货率高达 31%。这个类目值得关注。")
        cleaned, dropped = evidence.validate_citations({"summary": text}, self.allowed)
        self.assertIn("512", cleaned["summary"])
        self.assertNotIn("31%", cleaned["summary"])
        self.assertIn("这个类目值得关注", cleaned["summary"])
        self.assertTrue(any("uncited-number" in d for d in dropped))

    def test_prose_without_numbers_survives_uncited(self) -> None:
        text = "This category rewards design differentiation.\nThe incumbents look tired."
        cleaned, dropped = evidence.validate_citations({"summary": text}, self.allowed)
        self.assertEqual(cleaned["summary"], text)
        self.assertEqual(dropped, [])

    def test_a_markdown_link_to_an_unknown_id_degrades_to_text(self) -> None:
        text = "Revenue rose [ev_nope00000000](evidence:ev_nope00000000) sharply.\nmore"
        cleaned, dropped = evidence.validate_citations({"summary": text}, self.allowed)
        self.assertNotIn("evidence:ev_nope", cleaned["summary"])
        self.assertTrue(any("unknown-id" in d for d in dropped))

    def test_table_rows_and_headings_are_not_sentences(self) -> None:
        """The digit rule would otherwise shred a table whose every cell is a number."""
        text = "## 价格带\n| 区间 | 占比 |\n| --- | --- |\n| 50-100 | 22.8% |"
        cleaned, dropped = evidence.validate_citations({"summary": text}, self.allowed)
        self.assertIn("22.8%", cleaned["summary"])
        self.assertEqual(dropped, [])

    def test_short_labels_are_left_alone(self) -> None:
        payload = {"verdict": "enter", "price_band": "$429-$519", "score_label": "78"}
        cleaned, dropped = evidence.validate_citations(payload, self.allowed)
        self.assertEqual(cleaned["price_band"], "$429-$519")
        self.assertEqual(cleaned["score_label"], "78")
        self.assertEqual(dropped, [])

    def test_nested_structures_are_walked(self) -> None:
        payload = {"sections": {"pain": {"themes": [
            {"theme": "kept", "evidence_ids": [self.known]},
            {"theme": "dropped", "evidence_ids": ["ev_000000000000"]},
        ]}}}
        cleaned, _ = evidence.validate_citations(payload, self.allowed)
        themes = cleaned["sections"]["pain"]["themes"]
        self.assertEqual([t["theme"] for t in themes], ["kept"])

    def test_notes_explain_what_was_removed(self) -> None:
        notes = evidence.citation_notes(
            ["$.a", "$.b:uncited-number", "$.c:unknown-id:ev_x"], language="zh")
        self.assertEqual(len(notes), 3)
        english = evidence.citation_notes(["$.a"], language="en")
        self.assertIn("conclusion", english[0])

    def test_no_drops_means_no_notes(self) -> None:
        self.assertEqual(evidence.citation_notes([]), [])


class SheetFormattingTests(unittest.TestCase):
    """Shares are stored as fractions and must not be read out as fractions."""

    def test_a_share_is_printed_as_a_percentage(self) -> None:
        index = evidence.EvidenceIndex(marketplace="US", period="202609")
        index.mint(subject_kind="node", subject_id="n", metric="return_ratio",
                   value=0.0177, tool="market_research", unit="share")
        sheet = index.sheet(language="zh")
        self.assertIn("1.77", sheet)
        self.assertNotIn("0.02", sheet)

    def test_a_small_share_keeps_enough_digits_to_survive(self) -> None:
        """Two decimals on the fraction would turn 1.77% into 0.02."""
        index = evidence.EvidenceIndex(marketplace="US", period="202609")
        index.mint(subject_kind="node", subject_id="n", metric="new_ratio_l12",
                   value=0.0042, tool="market_research", unit="share")
        self.assertIn("0.42", index.sheet(language="en"))

    def test_non_share_units_are_left_alone(self) -> None:
        index = evidence.EvidenceIndex(marketplace="US", period="202609")
        index.mint(subject_kind="node", subject_id="n", metric="total_revenue",
                   value=7_920_000.0, tool="market_research", unit="usd")
        index.mint(subject_kind="keyword", subject_id="k",
                   metric="supply_demand_ratio", value=24.8,
                   tool="keyword_research", unit="ratio")
        sheet = index.sheet(language="en")
        self.assertIn("7,920,000", sheet)
        self.assertIn("24.80", sheet)


if __name__ == "__main__":
    unittest.main()
