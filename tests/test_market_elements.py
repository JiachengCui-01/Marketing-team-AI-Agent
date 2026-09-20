"""Design terms mined from the market's own words, and the lists built on them.

Runs on literals: the mining is text processing and the aggregation is
arithmetic, so none of this needs a database, a vendor or a model.

The old version of this file tested a hand-written vocabulary of fifty style
words. The tests that survived the rewrite are the ones that were really about
evidence bars rather than about the list.
"""
from __future__ import annotations

import hashlib
import unittest

from server.market import elements, gateway, render


def title(name: str, revenue: float, *, price: float | None = None,
          brand: str = "Demo", node: str = "n1") -> dict:
    return {"title": name, "revenue": revenue, "price": price, "brand": brand,
            "node_id_path": node}


def kw(keyword: str, searches: float, mom: float | None = None) -> dict:
    return {"keyword": keyword, "searches": searches, "searches_mom_pct": mom}


class TokenisingTests(unittest.TestCase):
    def test_function_words_never_become_terms(self) -> None:
        terms = elements._terms(elements._tokens("Cabinet with Storage for the Hallway"))
        self.assertNotIn("with", terms)
        self.assertNotIn("for the", terms)

    def test_a_bigram_is_not_formed_across_a_function_word(self) -> None:
        """'with storage' is 'storage'; gluing the preposition on splits the term."""
        terms = elements._terms(elements._tokens("Sideboard with Storage"))
        self.assertIn("storage", terms)
        self.assertNotIn("with storage", terms)

    def test_real_bigrams_survive(self) -> None:
        """'lift top' and 'solid wood' are single decisions either half misreports."""
        terms = elements._terms(elements._tokens("Solid Wood Lift Top Coffee Table"))
        self.assertIn("solid wood", terms)
        self.assertIn("lift top", terms)

    def test_a_bare_number_is_not_a_term(self) -> None:
        terms = elements._terms(elements._tokens("60 inch Sideboard"))
        self.assertNotIn("60", terms)


class ExclusionTests(unittest.TestCase):
    """What gets filtered is derived from the rows, not from a list."""

    def test_a_brand_name_is_excluded_because_the_rows_say_it_is_one(self) -> None:
        rows = elements.mine([
            title("VASAGLE Fluted Sideboard", 100.0, brand="VASAGLE"),
            title("VASAGLE Arched Cabinet", 100.0, brand="VASAGLE"),
        ])
        found = {r["term"] for r in rows}
        self.assertNotIn("vasagle", found)
        self.assertIn("fluted", found)

    def test_a_category_noun_is_dropped_once_the_sample_can_show_it(self) -> None:
        """'Sideboard' is in every sideboard listing; that is what makes it the
        category and what makes it useless as a differentiator."""
        products = [title(f"Sideboard Buffet Cabinet {i}", 100.0) for i in range(24)]
        products += [title("Sideboard Fluted Door", 100.0) for _ in range(6)]
        found = {r["term"] for r in elements.mine(products)}
        self.assertNotIn("sideboard", found)
        self.assertNotIn("sideboard fluted", found)   # the category noun in a pair
        # Which phrasing survives is the deduper's call — here every fluted
        # listing says "fluted door", so that is the term the market uses.
        self.assertTrue([t for t in found if "fluted" in t], found)

    def test_a_small_node_does_not_have_its_best_style_filtered_as_a_noun(self) -> None:
        """In a node of four titles, three is both a category noun and a hit."""
        products = [title("Fluted Oak Sideboard", 100.0),
                    title("Fluted Door Console", 100.0),
                    title("Fluted Arch Cabinet", 100.0),
                    title("Tufted Velvet Bench", 100.0)]
        self.assertIn("fluted", {r["term"] for r in elements.mine(products)})


class ShelfTests(unittest.TestCase):
    LISTINGS = [
        title("Fluted Oak Sideboard Buffet", 600_000.0, price=429.0),
        title("Fluted Door Console Table", 200_000.0, price=289.0),
        title("Tufted Velvet Bench", 100_000.0, price=199.0),
        title("Plain Storage Cabinet", 100_000.0, price=149.0),
    ]

    def rows(self, products=None) -> dict[str, dict]:
        return {r["term"]: r for r in elements.mine(products or self.LISTINGS)}

    def test_share_is_of_revenue_not_of_listing_count(self) -> None:
        """Ten listings nobody buys prove a style is available, not that it works."""
        rows = self.rows()
        self.assertEqual(rows["fluted"]["revenue_share_pct"], 80.0)
        self.assertEqual(rows["fluted"]["asins"], 2)
        self.assertEqual(rows["tufted"]["revenue_share_pct"], 10.0)

    def test_a_listing_counts_toward_every_term_it_carries(self) -> None:
        rows = self.rows()
        self.assertEqual(rows["oak"]["revenue_share_pct"], 60.0)
        # Shares deliberately sum past 100: they are not slices of a pie.
        self.assertGreater(sum(r["revenue_share_pct"] for r in rows.values()), 100.0)

    def test_average_price_comes_from_the_matched_listings(self) -> None:
        self.assertEqual(self.rows()["fluted"]["avg_price"], 359.0)

    def test_a_thin_term_is_recorded_but_not_shelf_rated(self) -> None:
        rows = self.rows()
        self.assertFalse(rows["tufted"]["shelf_rated"])
        self.assertEqual(rows["tufted"]["asins"], 1)

    def test_no_revenue_anywhere_gives_a_zero_share_not_a_crash(self) -> None:
        """Dividing by a zero total would print 'nan%' on every dot."""
        rows = {r["term"]: r for r in elements.mine([title("Fluted Cabinet", 0.0)])}
        self.assertEqual(rows["fluted"]["revenue_share_pct"], 0.0)

    def test_an_untitled_listing_still_enlarges_the_denominator(self) -> None:
        """It is real revenue we simply cannot attribute, so shares fall."""
        rows = self.rows(self.LISTINGS + [title("", 900_000.0)])
        self.assertLess(rows["fluted"]["revenue_share_pct"], 80.0)


class DedupeTests(unittest.TestCase):
    def test_a_bigram_that_carries_its_unigram_wins(self) -> None:
        """'lift top' on every listing that says 'lift' makes 'lift' redundant."""
        products = [title(f"Lift Top Coffee Table {i}", 100.0) for i in range(4)]
        found = {r["term"] for r in elements.mine(products)}
        self.assertIn("lift top", found)
        self.assertNotIn("lift", found)

    def test_a_broad_term_beats_one_phrasing_of_itself(self) -> None:
        products = [title("Fluted Oak Sideboard", 100.0),
                    title("Fluted Door Console", 100.0),
                    title("Fluted Arch Cabinet", 100.0)]
        found = {r["term"] for r in elements.mine(products)}
        self.assertIn("fluted", found)
        self.assertNotIn("fluted oak", found)


class GrowthWindowTests(unittest.TestCase):
    """Which window a growth number came from, and what must never be one."""

    def test_a_rank_movement_is_never_read_as_demand_growth(self) -> None:
        """ABA's 0.9951 is a rank ratio. It used to be read as 'up 99.51%'."""
        row = {"keyword": "reacher", "searches": 10_115_226,
               "rank_growth_rate": 0.9951, "search_rank": 1, "rank_12w": 234}
        self.assertEqual(elements._growth_of(row, {}), (None, ""))

    def test_month_over_month_wins_over_year_over_year(self) -> None:
        """They disagree constantly in a seasonal category, which is the point."""
        row = {"keyword": "boucle sofa", "searches": 9_000,
               "searches_mom_pct": -8.13, "searches_yoy_pct": 18.31}
        self.assertEqual(elements._growth_of(row, {}), (-8.13, elements.MOM))

    def test_a_stored_comparison_wins_over_both(self) -> None:
        row = {"keyword": "boucle sofa", "searches": 9_000,
               "searches_mom_pct": -8.13, "searches_yoy_pct": 18.31}
        value, window = elements._growth_of(row, {"boucle sofa": 6_000.0})
        self.assertEqual(window, elements.STORED)
        self.assertAlmostEqual(value, 50.0)

    def test_the_explicit_columns_are_percentages_and_are_not_second_guessed(self) -> None:
        """searchMonthlyCr is -8.13 for 'down 8.13%'. A heuristic that rescaled
        anything inside +-3 turned a real 3% move into 300%."""
        self.assertEqual(elements._growth_of({"searches_mom_pct": 3.0}, {})[0], 3.0)
        self.assertEqual(elements._growth_of({"searches_yoy_pct": 0.4}, {})[0], 0.4)

    def test_the_legacy_column_still_gets_the_old_guess(self) -> None:
        """Rows written before the split really did vary by source; this release
        writes no more of them, so the guess is confined to history."""
        self.assertEqual(elements._growth_of({"searches_growth": 0.25}, {})[0], 25.0)
        self.assertEqual(elements._growth_of({"searches_growth": 25.0}, {})[0], 25.0)

    def test_growth_is_search_weighted(self) -> None:
        """A 300% move on 40 searches is noise next to 12% on 40,000."""
        rows = {r["term"]: r for r in elements.mine(
            [], [kw("boucle sofa", 40_000, 12.0), kw("boucle chair", 40, 300.0)])}
        self.assertAlmostEqual(rows["boucle"]["growth_pct"], 12.3, places=1)


class EvidenceBarTests(unittest.TestCase):
    def one(self, *keywords) -> list[dict]:
        return elements.mine([], list(keywords))

    def test_a_single_phrase_is_never_a_trend(self) -> None:
        rising, _falling = elements.split(self.one(kw("japandi sideboard", 50_000, 60.0)))
        self.assertEqual(rising, [])

    def test_a_tiny_search_volume_is_never_a_trend(self) -> None:
        rising, _falling = elements.split(self.one(
            kw("terrazzo console", 300, 80.0), kw("terrazzo side table", 200, 75.0)))
        self.assertEqual(rising, [])

    def test_a_move_inside_the_band_is_neither(self) -> None:
        rising, falling = elements.split(self.one(
            kw("oak sideboard", 20_000, 3.0), kw("oak console table", 9_000, 2.0)))
        self.assertEqual((rising, falling), ([], []))

    def test_rising_and_falling_are_ordered_by_strength(self) -> None:
        rows = self.one(
            kw("fluted cabinet", 9_000, 40.0), kw("fluted console", 6_000, 35.0),
            kw("tufted sofa", 12_000, -30.0), kw("tufted bench", 7_000, -25.0))
        rising, falling = elements.split(rows)
        self.assertEqual([r["term"] for r in rising], ["fluted"])
        self.assertEqual([r["term"] for r in falling], ["tufted"])

    def test_a_phrase_with_no_growth_anywhere_leaves_the_term_unrated(self) -> None:
        rows = {r["term"]: r for r in self.one(
            kw("marble dining table", 9_000), kw("marble console", 5_000))}
        self.assertIsNone(rows["marble"]["growth_pct"])
        self.assertFalse(rows["marble"]["rated"])


class NamingTests(unittest.TestCase):
    """The model names and classifies; it computes nothing and adds nothing."""

    TERMS = [{"term": "fluted", "asins": 3, "revenue_share_pct": 21.0,
              "searches": 17_000, "growth_pct": 35.0, "rated": True,
              "shelf_rated": True, "keyword_count": 2, "keywords": [],
              "revenue": 1.0, "avg_price": 399.0, "window": "mom"}]

    def test_a_named_term_gets_its_label_and_kind(self) -> None:
        named = elements.apply_naming(
            self.TERMS, {"fluted": {"kind": "craft", "label_zh": "竖纹",
                                    "label_en": "Fluted"}}, True)
        self.assertEqual(named[0]["label"], "竖纹")
        self.assertEqual(named[0]["kind_label"], "工艺 · 纹样")

    def test_an_unnamed_term_keeps_its_own_words(self) -> None:
        """An unnamed real term is worth more than a named invented one."""
        named = elements.apply_naming(self.TERMS, {}, True)
        self.assertEqual(named[0]["label"], "fluted")
        self.assertEqual(named[0]["kind"], elements.OTHER)

    def test_a_term_the_model_dropped_disappears(self) -> None:
        named = elements.apply_naming(self.TERMS, {"fluted": {"drop": True}}, True)
        self.assertEqual(named, [])

    def test_an_invented_kind_falls_back_rather_than_reaching_the_ui(self) -> None:
        named = elements.apply_naming(
            self.TERMS, {"fluted": {"kind": "vibes", "label_zh": "竖纹"}}, True)
        self.assertEqual(named[0]["kind"], elements.OTHER)

    def test_the_numbers_survive_naming_untouched(self) -> None:
        named = elements.apply_naming(
            self.TERMS, {"fluted": {"kind": "form", "label_zh": "竖纹",
                                    "revenue_share_pct": 99.0, "searches": 1}}, True)
        self.assertEqual(named[0]["revenue_share_pct"], 21.0)
        self.assertEqual(named[0]["searches"], 17_000)


class CombinationTests(unittest.TestCase):
    """Specs, not elements. A single term is an alternative; a combination is a
    product, and a product is what a brief is written from."""

    NAMED = [
        {"term": "fluted", "kind": elements.CRAFT, "label": "竖纹",
         "kind_label": "工艺", "revenue_share_pct": 9.0},
        {"term": "oak", "kind": elements.MATERIAL, "label": "橡木",
         "kind_label": "材质", "revenue_share_pct": 8.0},
        {"term": "walnut", "kind": elements.MATERIAL, "label": "胡桃木",
         "kind_label": "材质", "revenue_share_pct": 3.0},
        {"term": "black", "kind": elements.COLOR, "label": "黑色",
         "kind_label": "颜色", "revenue_share_pct": 7.0},
        {"term": "clearance", "kind": elements.OTHER, "label": "清仓",
         "kind_label": "其他", "revenue_share_pct": 6.0},
    ]

    def products(self, titles: list[str], ratings: list[float] | None = None,
                 revenues: list[float] | None = None) -> list[dict]:
        rows = []
        for i, title in enumerate(titles):
            row = {"asin": f"B{i}", "brand": "Demo", "title": title,
                   "revenue": revenues[i] if revenues else 1_000.0,
                   "price": 300.0, "node_id_path": "n:1", "ratings": 100.0}
            if ratings:
                row["rating"] = ratings[i]
            rows.append(row)
        return rows

    def test_the_rating_is_weighted_by_revenue(self) -> None:
        """The rating a shopper meets is the one carried by the listings that
        actually sell — an average over every listing lets a dead one vote."""
        combos = elements.combinations(
            self.products(["Fluted Oak Sideboard"] * 5,
                          ratings=[5.0, 3.0, 3.0, 3.0, 3.0],
                          revenues=[900_000.0, 100.0, 100.0, 100.0, 100.0]),
            self.NAMED)
        spec = next(c for c in combos if c["key"] == "fluted+oak")
        self.assertGreater(spec["rating"], 4.9)
        self.assertEqual(spec["rated_asins"], 5)

    def test_a_spec_whose_listings_carry_no_rating_has_none(self) -> None:
        """Not zero stars: an unrated spec is one the chart rails rather than
        one the market hates."""
        combos = elements.combinations(
            self.products(["Fluted Oak Sideboard"] * 5), self.NAMED)
        spec = next(c for c in combos if c["key"] == "fluted+oak")
        self.assertIsNone(spec["rating"])
        self.assertEqual(spec["rated_asins"], 0)

    def test_the_review_count_is_the_median_not_the_sum(self) -> None:
        """It stands for the bar a new listing has to clear, which is a typical
        competitor rather than the whole shelf added up."""
        combos = elements.combinations(
            self.products(["Fluted Oak Sideboard"] * 5), self.NAMED)
        self.assertEqual(
            next(c for c in combos if c["key"] == "fluted+oak")["reviews"], 100)

    def test_a_spec_has_to_come_off_real_listings(self) -> None:
        """The cartesian product of the vocabulary would invent thousands of
        products nobody has made, each with a measured x axis."""
        combos = elements.combinations(
            self.products(["Fluted Oak Sideboard"] * 5), self.NAMED)
        keys = {c["key"] for c in combos}
        self.assertIn("fluted+oak", keys)
        # `black` is in the vocabulary and on no listing, so no spec carries it.
        self.assertFalse([k for k in keys if "black" in k])

    def test_one_term_per_attribute(self) -> None:
        """A spec says "the material is oak", not "the materials are oak and
        walnut" — and it has to pick the same one every month."""
        combos = elements.combinations(
            self.products(["Fluted Oak Walnut Sideboard"] * 5), self.NAMED)
        spec = next(c for c in combos)
        materials = [p for p in spec["spec"] if p["kind"] == elements.MATERIAL]
        self.assertEqual(len(materials), 1)
        # The higher-revenue term of the two, deterministically.
        self.assertEqual(materials[0]["label"], "橡木")

    def test_a_spec_on_too_few_listings_is_one_sellers_idea(self) -> None:
        combos = elements.combinations(
            self.products(["Fluted Oak Sideboard"] * (elements.MIN_COMBO_ASINS - 1)),
            self.NAMED)
        self.assertEqual(combos, [])

    def test_a_single_attribute_is_not_a_combination(self) -> None:
        """That is the element chart, and it already exists."""
        combos = elements.combinations(
            self.products(["Fluted Sideboard"] * 6), self.NAMED)
        self.assertEqual(combos, [])

    def test_a_non_attribute_kind_never_enters_a_spec(self) -> None:
        """`other` is the bucket for terms we could not place; a spec built out
        of one would read as a product decision that nobody made."""
        combos = elements.combinations(
            self.products(["Clearance Fluted Oak Sideboard"] * 6), self.NAMED)
        for combo in combos:
            with self.subTest(combo["key"]):
                self.assertNotIn("clearance", combo["terms"])

    def test_demand_needs_a_phrase_carrying_the_whole_spec(self) -> None:
        """A phrase for one half of a spec is not demand for the spec."""
        combos = elements.combinations(
            self.products(["Fluted Oak Sideboard"] * 6), self.NAMED,
            [{"keyword": "fluted sideboard", "searches": 40_000.0,
              "searches_mom_pct": 30.0},
             {"keyword": "oak sideboard", "searches": 40_000.0,
              "searches_mom_pct": 30.0}])
        spec = next(c for c in combos if c["key"] == "fluted+oak")
        self.assertIsNone(spec["growth_pct"],
                          "neither phrase carries both terms")
        self.assertFalse(spec["rated"])

    def test_a_phrase_carrying_the_whole_spec_is_demand_for_it(self) -> None:
        combos = elements.combinations(
            self.products(["Fluted Oak Sideboard"] * 6), self.NAMED,
            [{"keyword": "fluted oak sideboard", "searches": 40_000.0,
              "searches_mom_pct": 30.0}])
        spec = next(c for c in combos if c["key"] == "fluted+oak")
        self.assertEqual(spec["growth_pct"], 30.0)
        self.assertTrue(spec["rated"])

    def test_growth_is_never_blended_from_the_parts(self) -> None:
        """Averaging the constituent terms' growth would fill the chart with
        numbers nobody measured, on an axis that looks measured."""
        combos = elements.combinations(
            self.products(["Fluted Oak Sideboard"] * 6), self.NAMED,
            [{"keyword": "fluted sideboard", "searches": 90_000.0,
              "searches_mom_pct": 80.0}])
        spec = next(c for c in combos if c["key"] == "fluted+oak")
        self.assertIsNone(spec["growth_pct"])
        self.assertEqual(spec["searches"], 0)


class CategorySpecTests(unittest.TestCase):
    """Room × shelf × colour × look — what the opportunity quadrant plots.

    A look is only open or crowded *somewhere*: the same surface treatment can
    be three brands' property in nightstands and untouched in sideboards, and
    one number averaged over both categories reports neither.
    """

    NAMED = [
        {"term": "burl", "kind": elements.CRAFT, "label": "木瘤纹",
         "kind_label": "工艺 · 纹样", "revenue_share_pct": 9.0},
        {"term": "mid century", "kind": elements.STYLE, "label": "中古风",
         "kind_label": "风格", "revenue_share_pct": 6.0},
        {"term": "glass", "kind": elements.MATERIAL, "label": "玻璃",
         "kind_label": "材质", "revenue_share_pct": 5.0},
        {"term": "black", "kind": elements.COLOR, "label": "黑色",
         "kind_label": "颜色", "revenue_share_pct": 7.0},
        {"term": "walnut", "kind": elements.COLOR, "label": "胡桃色",
         "kind_label": "颜色", "revenue_share_pct": 4.0},
        {"term": "12 inch", "kind": elements.SIZE, "label": "12 寸",
         "kind_label": "尺寸", "revenue_share_pct": 8.0},
        {"term": "clearance", "kind": elements.OTHER, "label": "清仓",
         "kind_label": "其他", "revenue_share_pct": 6.0},
    ]
    NODES = {"n:night": {}, "n:side": {}}

    def rows(self, node: str, name: str, count: int, *, brands: list[str] | None = None,
             revenue: float = 1_000.0, tag: str = "a") -> list[dict]:
        return [{"asin": f"{tag}{i}", "node_id_path": node, "title": name,
                 "brand": (brands[i % len(brands)] if brands else "Acme"),
                 "revenue": revenue, "price": 300.0, "rating": 4.2, "ratings": 120}
                for i in range(count)]

    def specs(self, products: list[dict], **kwargs) -> dict[str, dict]:
        return {s["key"]: s for s in
                elements.category_specs(products, self.NAMED, self.NODES, **kwargs)}

    def test_the_same_look_in_two_categories_is_two_points(self) -> None:
        """Averaging them would hide the one shelf where it is still open."""
        specs = self.specs(self.rows("n:night", "Black Burl Nightstand", 6)
                           + self.rows("n:side", "Black Burl Sideboard", 6, tag="b"))
        self.assertEqual(set(specs), {"n:night|black|burl", "n:side|black|burl"})

    def test_a_size_is_a_decision_but_not_a_look(self) -> None:
        """"12 inch" beside "burl" would read as two ways of drawing the same
        thing. Sizes belong to the element table, not to this chart."""
        spec = self.specs(self.rows("n:night", "Black 12 Inch Nightstand", 6))
        self.assertEqual(list(spec), ["n:night|black|"])
        self.assertEqual([part["label"] for part in spec["n:night|black|"]["spec"]],
                         ["黑色"])

    def test_a_structural_part_is_not_a_look(self) -> None:
        """"黑色 · 搁板" is a true sentence and not a design decision. While
        shelves and silhouettes shared the `form` kind, a structural noun kept
        winning the one look slot and the quadrant recommended cabinets by
        their shelves."""
        named = list(self.NAMED) + [
            {"term": "shelf", "kind": elements.PART, "label": "搁板",
             "kind_label": "部件", "revenue_share_pct": 30.0}]
        specs = {s["key"]: s for s in elements.category_specs(
            self.rows("n:night", "Black Shelf Burl Nightstand", 6), named,
            self.NODES)}
        self.assertEqual(list(specs), ["n:night|black|burl"])
        self.assertNotIn("搁板", str(specs["n:night|black|burl"]["spec"]))

    def test_a_silhouette_is_a_look(self) -> None:
        """Wavy, arched and low profile are what a buyer sees across a room."""
        named = list(self.NAMED) + [
            {"term": "wavy", "kind": elements.FORM, "label": "波浪流线",
             "kind_label": "外形", "revenue_share_pct": 2.0}]
        specs = {s["key"]: s for s in elements.category_specs(
            self.rows("n:night", "Black Wavy Nightstand", 6), named, self.NODES)}
        self.assertEqual(specs["n:night|black|wavy"]["look"], "波浪流线")

    def test_a_surface_treatment_wins_the_one_look_slot(self) -> None:
        """Nearly every title names a material, so taking the material first
        would fill the chart with "glass" and hide every treatment behind it."""
        spec = self.specs(self.rows("n:night", "Black Burl Glass Nightstand", 6))
        self.assertEqual(list(spec), ["n:night|black|burl"])

    def test_a_non_attribute_kind_never_enters_a_spec(self) -> None:
        spec = self.specs(self.rows("n:night", "Clearance Black Nightstand", 6))
        self.assertEqual(list(spec), ["n:night|black|"])

    def test_a_cell_on_too_few_listings_is_one_sellers_idea(self) -> None:
        self.assertEqual(
            self.specs(self.rows("n:night", "Black Burl Nightstand",
                                 elements.MIN_SPEC_ASINS - 1)),
            {})

    def test_a_listing_naming_neither_is_not_a_spec_but_is_still_the_shelf(self) -> None:
        """The plain titles are the denominator. Leaving them out would inflate
        every cell by however much of the shelf writes copy without adjectives."""
        specs = self.specs(self.rows("n:night", "Black Burl Nightstand", 6)
                           + self.rows("n:night", "Nightstand", 6, tag="p"))
        self.assertEqual(list(specs), ["n:night|black|burl"])
        self.assertEqual(specs["n:night|black|burl"]["share_pct"], 50.0)

    def test_absent_last_month_is_a_measured_zero(self) -> None:
        """A look that did not exist and now holds a third of the shelf is the
        most interesting row on the chart; dropping it for having no
        predecessor would delete exactly the specs worth finding."""
        specs = self.specs(
            self.rows("n:night", "Black Burl Nightstand", 6)
            + self.rows("n:night", "Nightstand", 6, tag="p"),
            before=self.rows("n:night", "Nightstand", 12, tag="p"))
        self.assertEqual(specs["n:night|black|burl"]["share_before_pct"], 0.0)
        self.assertEqual(specs["n:night|black|burl"]["share_shift_pp"], 50.0)

    def test_a_shelf_with_no_comparison_month_keeps_x_and_loses_y(self) -> None:
        """Unmeasured is not zero. The chart rails this one instead of drawing
        it as a spec that held its share exactly."""
        specs = self.specs(self.rows("n:night", "Black Burl Nightstand", 6),
                           before=self.rows("n:side", "Black Burl Sideboard", 6))
        spec = specs["n:night|black|burl"]
        self.assertIsNone(spec["share_shift_pp"])
        self.assertIsNone(spec["share_before_pct"])
        self.assertIsNotNone(spec["entry"])

    def test_the_shift_is_share_rather_than_revenue_growth(self) -> None:
        """Twice as many listings collected this month doubles every cell's
        revenue and moves no share. One of those is a measurement."""
        before = (self.rows("n:night", "Black Burl Nightstand", 6)
                  + self.rows("n:night", "Nightstand", 6, tag="p"))
        now = (self.rows("n:night", "Black Burl Nightstand", 12, revenue=2_000.0)
               + self.rows("n:night", "Nightstand", 12, revenue=2_000.0, tag="p"))
        specs = self.specs(now, before=before)
        self.assertEqual(specs["n:night|black|burl"]["share_shift_pp"], 0.0)

    def test_entry_is_what_the_three_largest_brands_left(self) -> None:
        """The board's 可进入度 is ``100 - top5 brand share``. Top five is
        degenerate at this grain — six listings have five brands in their top
        five whatever the shelf looks like — so it is the top three."""
        specs = self.specs(self.rows("n:night", "Black Burl Nightstand", 6,
                                     brands=["A", "A", "A", "B", "C", "D"]))
        # A holds three sixths, B and C one each: five of six, so one is left.
        self.assertEqual(specs["n:night|black|burl"]["entry"], 16.7)
        self.assertEqual(specs["n:night|black|burl"]["brands"], 4)

    def test_an_unrecorded_brand_counts_as_its_own_owner(self) -> None:
        """Missing data may leave a cell looking open; it must never invent a
        monopoly out of six blank brand columns."""
        specs = self.specs(self.rows("n:night", "Black Burl Nightstand", 6,
                                     brands=[""]))
        self.assertEqual(specs["n:night|black|burl"]["entry"], 50.0)

    def test_measuring_a_cell_is_not_the_same_as_plotting_it(self) -> None:
        """Every cell that clears the listing bar comes back, however many that
        is. Capping here would make the count beside the chart report how many
        specs survived a cap rather than how many the shelf has — and it would
        decide which categories get drawn in the module that cannot see the
        chart."""
        named = list(self.NAMED) + [
            {"term": f"c{i}", "kind": elements.COLOR, "label": f"色{i}",
             "kind_label": "颜色", "revenue_share_pct": 1.0} for i in range(20)]
        products: list[dict] = []
        for i in range(20):
            products += self.rows("n:side", f"C{i} Burl Sideboard", 6,
                                  revenue=10_000.0, tag=f"s{i}")
        products += self.rows("n:night", "Black Burl Nightstand", 6, revenue=1.0,
                              tag="n")
        specs = {s["key"]: s for s in
                 elements.category_specs(products, named, self.NODES)}
        self.assertIn("n:night|black|burl", specs)
        self.assertEqual(len([k for k in specs if k.startswith("n:side|")]), 20)

    def test_the_spec_is_named_row_by_row_for_the_card(self) -> None:
        """"颜色 黑色 · 工艺 · 纹样 木瘤纹" reads; a glued string does not."""
        spec = self.specs(self.rows("n:night", "Black Burl Nightstand", 6))
        rows = spec["n:night|black|burl"]["spec"]
        self.assertEqual([(r["kind_label"], r["label"]) for r in rows],
                         [("颜色", "黑色"), ("工艺 · 纹样", "木瘤纹")])

    def test_nothing_named_means_no_chart_rather_than_an_empty_grid(self) -> None:
        self.assertEqual(elements.category_specs(
            self.rows("n:night", "Black Burl Nightstand", 6), [], self.NODES), [])

    def test_a_listing_outside_the_tracked_nodes_is_not_a_shelf(self) -> None:
        """Department roll-ups carry the same ASINs as their children; counting
        them would put every listing on the chart twice."""
        self.assertEqual(
            self.specs(self.rows("n:rollup", "Black Burl Nightstand", 6)), {})


class BriefTests(unittest.TestCase):
    def test_an_empty_read_produces_no_block(self) -> None:
        """An empty heading in the prompt is worse than no heading."""
        self.assertEqual(elements.brief([], [], True), "")

    def test_the_naming_brief_carries_the_measurements_as_final(self) -> None:
        text = elements.naming_brief([
            {"term": "fluted", "asins": 3, "revenue_share_pct": 21.0, "searches": 17_000}])
        self.assertIn("fluted | 3 | 21.0% | 17,000", text)
        self.assertIn("never evaluate", text)

    def test_the_naming_brief_states_the_kind_rules(self) -> None:
        """They lived in the tool schema alone once, and the first production run
        put every colour under `style` and left `craft` empty."""
        text = elements.naming_brief([
            {"term": "burl", "asins": 4, "revenue_share_pct": 3.0, "searches": 9_000}])
        for kind in elements.KINDS:
            self.assertIn(kind, text)
        self.assertIn("fluted", text)
        self.assertIn("never `style`", text)


class NamingVersionGuardTests(unittest.TestCase):
    """Editing the kind vocabulary without bumping the version fails here.

    The version is what re-asks the model for terms classified under an older
    list of kinds, and it is hand-maintained on purpose — a hash of the prompt
    would re-spend on every comment reflow, and the "# 3: …" notes beside it are
    documentation a hash cannot carry. What hand-maintenance lacks is a reminder,
    and the last release proved it: version 2 shipped with `craft` and `color`
    available and the rules still only in the tool schema, so every colour came
    back filed under `style`.

    This is that reminder. When the vocabulary below changes, the expected digest
    changes with it and this test fails until someone decides — deliberately —
    whether the edit was semantic enough to re-ask the model for every term.
    """

    # Bump NAMING_VERSION and then paste the digest this test prints.
    EXPECTED = "4b005e1a50c57c6e"

    def digest(self) -> str:
        material = "\n".join([
            repr(elements.KINDS), repr(elements.KIND_ORDER),
            repr(sorted(elements.KIND_LABELS.items())), elements._KIND_RULES,
        ])
        return hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]

    def test_the_vocabulary_matches_the_version_it_was_stamped_with(self) -> None:
        self.assertEqual(
            self.digest(), self.EXPECTED,
            f"The kind vocabulary changed. Decide whether cached classifications "
            f"are now wrong: if they are, bump elements.NAMING_VERSION (currently "
            f"{elements.NAMING_VERSION}) so they are re-asked. Either way, set "
            f"EXPECTED to {self.digest()!r}.")

    def test_every_kind_is_offered_to_the_model(self) -> None:
        """A kind the tool schema does not list can never be assigned, and
        `apply_naming` silently rewrites the unknown answer to `other`."""
        schema = render.TOOL_ELEMENTS["input_schema"]["properties"]["terms"]
        offered = schema["items"]["properties"]["kind"]["enum"]
        self.assertEqual(sorted(offered), sorted(elements.KINDS))

    def test_every_kind_is_explained_in_the_brief(self) -> None:
        for kind in elements.KINDS:
            with self.subTest(kind):
                self.assertIn(kind, elements._KIND_RULES)


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
