"""Design elements, discovered from the data rather than declared in advance.

A category tells a product team *where* to work. It does not tell them what to
draw. "Sideboards are growing 12%" is not a brief; "fluted fronts hold 21% of
head revenue and their phrases are up 36%" is — one of those sentences can be
handed to a designer.

This module used to answer that from a hand-written vocabulary of fifty style
words. That was wrong in a way worth stating plainly: a fixed list can only find
what somebody thought of before the data arrived. It cannot see a material that
appeared last quarter, it silently scores zero for anything phrased differently,
and it encodes one person's guess about what matters as though it were a
measurement. The market names its own styles; the job is to read those names off
the shelf and out of the search box.

So the terms are **mined**, the numbers are **computed**, and only the naming and
classification go to the model — the same division this package already uses for
review themes, and for the same reason. A model asked to "find the trending
styles" invents plausible ones at a steady rate. A model handed forty measured
terms and asked which is a material, which a form, and which is not a design
attribute at all is doing the one job it does better than a regex.

What gets filtered out is derived, not listed:

* **Category nouns** — a term in more than ``MAX_DOC_FREQ`` of a node's titles
  describes the category, not a choice inside it. "Sideboard" appears in every
  sideboard listing; that is what makes it the category and what makes it
  useless as a differentiator.
* **Brand names** — read from the ``brand`` column of the same rows, so a brand
  that starts showing up in titles next month is excluded next month too.
* **Function words** — the one genuinely fixed list here, and it is linguistic
  rather than domain: "with", "for", "and" are not furniture judgements.
"""
from __future__ import annotations

import re
from typing import Any, Iterable, Mapping, Sequence

from .scoring import _num

# Kinds the model may assign. An enum rather than free text so the UI can group
# by it and so two runs cannot produce both "material" and "materials".
#
# `craft` and `colour` are separate kinds rather than shades of `style` because
# they are separate decisions on a drawing. "Fluted" and "burl" are things the
# factory does to a surface — a tooling quote and a lead time; "walnut" is what
# the surface is; "black" is what it is finished in. Folding all three into one
# axis is what made the old chart unreadable: a size, a material and a colour
# sat side by side with nothing to say which comparison was meaningful.
MATERIAL, FORM, FEATURE, SIZE, COLOR, CRAFT, STYLE, ROOM, OTHER = (
    "material", "form", "feature", "size", "color", "craft", "style", "room",
    "other")
KINDS = (MATERIAL, FORM, FEATURE, SIZE, COLOR, CRAFT, STYLE, ROOM, OTHER)

KIND_LABELS: dict[str, tuple[str, str]] = {
    MATERIAL: ("材质", "Material"),
    FORM: ("形态", "Form"),
    FEATURE: ("功能", "Feature"),
    SIZE: ("尺寸", "Size"),
    COLOR: ("颜色", "Colour"),
    CRAFT: ("工艺 · 纹样", "Craft and pattern"),
    STYLE: ("风格", "Style"),
    ROOM: ("空间", "Room"),
    OTHER: ("其他", "Other"),
}

# Reading order for the grouped chart: the decisions a designer makes first come
# first. `other` is last and is the bucket a reader should be able to ignore.
KIND_ORDER = (CRAFT, MATERIAL, COLOR, SIZE, FORM, FEATURE, STYLE, ROOM, OTHER)

# Bumped whenever the kind vocabulary or the classification rules change. Naming
# is cached per term and never expires — without a version, every term
# classified before `craft` and `color` existed would keep the kind it was given
# when they did not, and the new columns would fill up only with terms the market
# happened to coin since.
#
# 3: the rules moved from the tool schema into the brief. Version 2 shipped with
# both kinds available and still filed 白色 and 黑色 under `style`, so those rows
# are a wrong answer rather than an old one and have to be asked again.
# 4: `other` had become the default rather than the last resort — 123 of ~150
# terms, with rooms, materials and structural nouns inside it. Every one of
# those rows is in the wrong column, so the whole vocabulary is re-asked.
NAMING_VERSION = 4

# Syntax, not domain: a bigram must not be glued across one of these, or
# "cabinet with storage" becomes the term "with storage".
_FUNCTION_WORDS = frozenset("""
a an and are as at be but by for from has have in into is it its of off on or
over per the their this to under up use used using via was were what when which
who will with without your you our we all any both each few more most other
some such than that these those too very can just not no nor own same so
""".split())

# Words that mean nothing alone but carry a real term when paired. "top" is
# marketing copy; "lift top" is a mechanism. "inch" is a unit; "12 inch" is a
# dimension decision. So these are barred as terms in their own right and
# allowed inside a pair — which is the difference between filtering noise and
# deleting the vocabulary.
_WEAK_WORDS = frozenset("""
inch inches cm mm ft feet lb lbs kg pound pounds count size sized
set pack piece pieces pcs pc x new best top great high low home style styles
design designs quality premium
""".split())

# A term this common inside one node is that node's own name for itself.
# Deliberately high: a real category noun is in nearly every title ("sideboard"
# in Sideboards), while a style that is genuinely winning can easily reach half.
# Cutting at 45% would have deleted the most successful element on the shelf and
# called it a filter. What slips through goes to the model's `drop` flag, which
# is the right place for a judgement call.
MAX_DOC_FREQ = 0.6
# Below this many listings, document frequency cannot tell a category noun from a
# popular style — in a node of four titles, three is both.
MIN_DOCS_FOR_DF = 20
# Below this a term is one listing's copywriting, not a market signal.
MIN_TITLE_ASINS = 3
MIN_KEYWORDS = 2
# The demand bar. 3,000 a month was set when every element competed for one of
# forty slots on a single scatter, so the bar was doing two jobs: proving a term
# is real, and rationing a list. Only the first is its job. Split across nine
# attributes, 3,000 was deleting whole categories of genuine decision — a front
# profile that 1,500 people a month search for is a brief, not noise — and the
# dot area already encodes volume, so a thin signal arrives looking thin.
MIN_SEARCHES = 1_200.0
# How many mined terms are worth putting in front of the model to name.
# Forty was set when every element shared one scatter, where forty dots is
# already past readable. Split across nine attribute rows it left most of them
# with two or three points — a colour row that knows about white and black only
# is worse than no colour row. Naming is cached per term and batched, so the
# longer list costs a few model calls the first time a term appears and nothing
# after that.
#
# 160 was binding in production: one attribute row reported 123 elements of a
# mined list that had nowhere else to go, which means the cap — not the market —
# was deciding what the tail looked like. The per-attribute caps are the ones
# that should shape the chart; this one only bounds the read.
MAX_TERMS = 260
# Stored rows the mining may take in. Ceilings on a SELECT over data already
# collected and already paid for, set high enough not to bind rather than tuned
# — the evidence bars above are what decide what counts. They live here rather
# than beside the chart's caps because they bound the *read*, not the layout.
MAX_TITLE_ROWS = 20_000
MAX_PHRASE_ROWS = 8_000
# Terms per naming call. The model's answer is ~40 tokens a term and DeepSeek
# caps output at 8k, so one call for the whole list would be truncated — and a
# truncated tool call is not a partial answer, it is no answer at all, which
# would leave a whole month unnamed. Batched, a failure costs one chunk.
NAMING_BATCH = 50

RISING_PCT = 10.0
FALLING_PCT = -10.0

# Which window a growth figure came from. Reported alongside the number because
# "up 18%" means different things over a month and over a year, and a seasonal
# category will disagree with itself between the two.
STORED, MOM, YOY = "stored", "mom", "yoy"

_WORD = re.compile(r"[a-z][a-z0-9\-']*|\d+(?:\.\d+)?")


def kind_label(kind: str, zh: bool) -> str:
    names = KIND_LABELS.get(kind, (kind, kind))
    return names[0] if zh else names[1]


# ------------------------------------------------------------------ mining ----

def _tokens(text: str) -> list[str]:
    return [w for w in _WORD.findall((text or "").lower()) if len(w) > 1]


def _terms(tokens: Sequence[str]) -> set[str]:
    """Unigrams and bigrams, function words dropped from both.

    Bigrams matter: "lift top" and "solid wood" are single design decisions that
    either half alone would misrepresent. A bigram with a function word at an
    edge is not formed at all — "with storage" is "storage".
    """
    out: set[str] = set()
    out.update(t for t in tokens
               if t not in _FUNCTION_WORDS and t not in _WEAK_WORDS and not t.isdigit())
    for left, right in zip(tokens, tokens[1:]):
        if left in _FUNCTION_WORDS or right in _FUNCTION_WORDS:
            continue
        out.add(f"{left} {right}")
    return out


def _brand_terms(rows: Iterable[Mapping[str, Any]]) -> set[str]:
    """Brand names as they appear in the same rows, so the exclusion ages with them."""
    out: set[str] = set()
    for row in rows:
        for token in _tokens(str(row.get("brand") or "")):
            if token not in _FUNCTION_WORDS:
                out.add(token)
    return out


def mine(products: Sequence[Mapping[str, Any]],
         keywords: Sequence[Mapping[str, Any]] = (),
         *, previous: Sequence[Mapping[str, Any]] = ()) -> list[dict]:
    """Discover the terms the market itself uses, with both halves measured.

    Supply comes from listing titles weighted by revenue — ten listings nobody
    buys prove a style is *available*, not that it works. Demand comes from the
    search phrases carrying the same term. A term found on only one side is kept:
    demand with no shelf behind it is the most interesting reading there is.
    """
    total_revenue = sum((_num(p.get("revenue")) or 0.0) for p in products)
    brands = _brand_terms(products)

    # Document frequency is per node: "desk" is the category in Home Office Desks
    # and a genuine feature term in Sideboards.
    by_node: dict[str, list[set[str]]] = {}
    rows: list[tuple[set[str], float, float | None]] = []
    for product in products:
        title = str(product.get("title") or "")
        if not title:
            continue
        terms = _terms(_tokens(title))
        by_node.setdefault(str(product.get("node_id_path") or ""), []).append(terms)
        rows.append((terms, _num(product.get("revenue")) or 0.0,
                     _num(product.get("price"))))

    common: set[str] = set()
    for docs in by_node.values():
        if len(docs) < MIN_DOCS_FOR_DF:
            continue
        counts: dict[str, int] = {}
        for terms in docs:
            for term in terms:
                counts[term] = counts.get(term, 0) + 1
        common |= {term for term, hits in counts.items()
                   if hits / len(docs) > MAX_DOC_FREQ}

    # Memoised, because this is asked once per term *occurrence*: twenty thousand
    # titles at ~18 terms each is on the order of 350k calls for a distinct term
    # set a fraction that size, and "oak" gets the same answer on every listing
    # that mentions it.
    verdicts: dict[str, bool] = {}

    def excluded(term: str) -> bool:
        cached = verdicts.get(term)
        if cached is None:
            cached = any(part in common or part in brands
                         for part in term.split(" "))
            verdicts[term] = cached
        return cached

    shelf: dict[str, dict] = {}
    for terms, revenue, price in rows:
        for term in terms:
            if excluded(term):
                continue
            bucket = shelf.setdefault(term, {"asins": 0, "revenue": 0.0, "_prices": []})
            bucket["asins"] += 1
            bucket["revenue"] += revenue
            if price is not None:
                bucket["_prices"].append(price)

    demand = _demand_terms(keywords, previous, excluded=excluded)

    out: list[dict] = []
    for term in set(shelf) | set(demand):
        supply = shelf.get(term) or {"asins": 0, "revenue": 0.0, "_prices": []}
        want = demand.get(term) or {}
        prices = supply.get("_prices") or []
        out.append({
            "term": term,
            "asins": supply["asins"],
            "revenue": round(supply["revenue"], 2),
            "revenue_share_pct": (round(supply["revenue"] / total_revenue * 100.0, 1)
                                  if total_revenue > 0 else 0.0),
            "avg_price": round(sum(prices) / len(prices), 2) if prices else None,
            "shelf_rated": supply["asins"] >= MIN_TITLE_ASINS,
            "searches": int(want.get("searches") or 0),
            "keyword_count": int(want.get("keyword_count") or 0),
            "growth_pct": want.get("growth_pct"),
            "window": want.get("window") or "",
            "keywords": want.get("keywords") or [],
            "rated": bool(want.get("rated")),
        })
    # Ranked by the money first: a term nobody sells is worth reading only after
    # the terms somebody sells.
    out.sort(key=lambda t: (t["revenue_share_pct"], t["searches"]), reverse=True)
    return _dedupe(out)[:MAX_TERMS]


def _demand_terms(keywords: Sequence[Mapping[str, Any]],
                  previous: Sequence[Mapping[str, Any]],
                  *, excluded) -> dict[str, dict]:
    before = {str(r.get("keyword") or ""): _num(r.get("searches")) or 0.0
              for r in previous}
    buckets: dict[str, dict] = {}
    for row in keywords:
        phrase = str(row.get("keyword") or "").strip()
        if not phrase:
            continue
        searches = _num(row.get("searches")) or 0.0
        growth, window = _growth_of(row, before)
        for term in _terms(_tokens(phrase)):
            if excluded(term):
                continue
            bucket = buckets.setdefault(term, {
                "searches": 0.0, "keyword_count": 0, "keywords": [],
                "_weighted": 0.0, "_weight": 0.0, "_windows": {},
            })
            bucket["searches"] += searches
            bucket["keyword_count"] += 1
            bucket["keywords"].append({"keyword": phrase, "searches": searches,
                                       "growth_pct": growth})
            if growth is not None and searches > 0:
                bucket["_weighted"] += growth * searches
                bucket["_weight"] += searches
                bucket["_windows"][window] = bucket["_windows"].get(window, 0.0) + searches

    for bucket in buckets.values():
        weight = bucket.pop("_weight")
        weighted = bucket.pop("_weighted")
        windows = bucket.pop("_windows")
        # Search-weighted: a 300%-growth phrase with 40 searches a month is noise
        # next to a 12% move on a phrase with 40,000.
        bucket["growth_pct"] = round(weighted / weight, 1) if weight else None
        bucket["window"] = max(windows, key=windows.get) if windows else ""
        bucket["keywords"] = sorted(bucket["keywords"],
                                    key=lambda k: k["searches"], reverse=True)[:5]
        bucket["searches"] = round(bucket["searches"])
        bucket["rated"] = bool(bucket["growth_pct"] is not None
                               and bucket["keyword_count"] >= MIN_KEYWORDS
                               and bucket["searches"] >= MIN_SEARCHES)
    return buckets


def _dedupe(terms: Sequence[dict]) -> list[dict]:
    """Drop a unigram a bigram already says better, and vice versa.

    "fluted" and "fluted door" are mined from the same listings. Keeping both
    puts one design decision on the chart twice and splits nothing. The narrower
    term wins when it carries nearly all of the broader one; otherwise the
    broader term is the real one and the bigram is one phrasing of it.
    """
    by_term = {t["term"]: t for t in terms}
    covers: dict[str, list[str]] = {}
    drop: set[str] = set()
    for term, row in by_term.items():
        if " " not in term:
            continue
        for half in term.split(" "):
            parent = by_term.get(half)
            if parent is None:
                continue
            # The pair only displaces the single word when it is substantial in
            # its own right and covers nearly all of it. Without the first
            # condition a one-off phrasing ("oak sideboard", seen once) would
            # delete the material it mentions.
            if row["asins"] >= max(MIN_TITLE_ASINS, parent["asins"] * 0.8):
                covers.setdefault(half, []).append(term)
            else:
                drop.add(term)
    for half, pairs in covers.items():
        if half in drop:
            continue
        # Covered by exactly one pair: the market always says it the same way, so
        # the pair is the term. Covered by several: the word appears in varied
        # phrasings, which is what makes the word itself the term.
        if len(pairs) == 1 and pairs[0] not in drop:
            drop.add(half)
        else:
            drop.update(pairs)
    return [t for t in terms if t["term"] not in drop]


def _growth_of(row: Mapping[str, Any],
               previous: Mapping[str, float] | None) -> tuple[float | None, str]:
    """``(percent, window)`` — never a rank movement dressed up as demand growth.

    ``rank_growth_rate`` is deliberately not consulted. It is ABA's *rank*
    movement, where lower is better and the scale is a ratio of positions; the
    old code fell back to it whenever ``growth`` was absent, so an ABA-sourced
    phrase reported 0.9951 as "up 99.51%".
    """
    keyword = str(row.get("keyword") or "")
    now = _num(row.get("searches"))
    before = (previous or {}).get(keyword)
    if now is not None and before:
        return (now - before) / before * 100.0, STORED
    for column, window in (("searches_mom_pct", MOM), ("searches_yoy_pct", YOY)):
        value = _num(row.get(column))
        if value is not None:
            # These two are percentages by definition — searchMonthlyCr is -8.13
            # for "down 8.13%". No guessing, and so no way for a real 3% move to
            # be inflated a hundredfold.
            return value, window
    # The legacy column, written before the two windows were separated. Its unit
    # genuinely varied by source, so here the guess is unavoidable; it is confined
    # to rows this release will never write again.
    legacy = _num(row.get("searches_growth"))
    if legacy is None:
        return None, ""
    return (legacy * 100.0 if -3.0 < legacy < 3.0 else legacy), MOM


# ------------------------------------------------------------------ naming ----
# The model's only job here: say what each mined term *is*, in the reader's
# language, and drop the ones that are not design attributes. It computes
# nothing — every number above survives untouched.

def apply_naming(terms: Sequence[dict], naming: Mapping[str, Mapping[str, Any]],
                 zh: bool) -> list[dict]:
    """Attach labels and kinds, dropping what the model marked as not an attribute.

    A term the model did not answer for keeps its own words as its label. An
    unnamed real term is worth more than a named invented one, and the whole
    point of mining is that the vocabulary is not ours to pre-approve.
    """
    out: list[dict] = []
    for row in terms:
        entry = naming.get(row["term"]) or {}
        if entry.get("drop"):
            continue
        kind = str(entry.get("kind") or OTHER)
        if kind not in KINDS:
            kind = OTHER
        label = str(entry.get("label_zh" if zh else "label_en") or "").strip()
        out.append({**row, "key": row["term"], "kind": kind,
                    "label": label or row["term"],
                    "kind_label": kind_label(kind, zh)})
    return out


def split(rows: Iterable[dict], *, limit: int = 6) -> tuple[list[dict], list[dict]]:
    """``(rising, falling)`` — only terms that cleared the evidence bar."""
    rated = [r for r in rows if r.get("rated")]
    rising = sorted([r for r in rated if (r["growth_pct"] or 0) >= RISING_PCT],
                    key=lambda r: r["growth_pct"], reverse=True)[:limit]
    falling = sorted([r for r in rated if (r["growth_pct"] or 0) <= FALLING_PCT],
                     key=lambda r: r["growth_pct"])[:limit]
    return rising, falling


# The kind rules live in the brief, not only in the tool's field description.
# They were only in the schema first, and the first production run filed 白色 and
# 黑色 under `style` and left `craft` empty — the model reads a user message far
# more carefully than an enum's `description`. Each line names the *decision* the
# kind stands for, because "is fluting a style?" has no answer while "is fluting
# a tooling decision or a mood?" does.
_KIND_RULES = """HOW TO CLASSIFY (exactly one kind per term).

`other` is a last resort, not a default. In the first production run it swallowed
123 of about 150 terms — including `bathroom`, `garage`, `bedroom` (those are
`room`), `shaped` and `corner` (`form`), `velvet` (`material`) and `drawers`
(`form`) — which left every other kind with three or four terms and made the
whole classification useless. Before answering `other`, go back through the list
above it and satisfy yourself that none of them fits. Almost always one does.

  material — what the thing is made of: solid wood, rattan, boucle, marble, mdf,
             velvet, linen, leather, glass, metal, bamboo
  craft    — what was done to the surface, or how it was built: a tooling and
             lead-time decision. fluted, reeded, burl / burl grain, cane weave,
             carved, tufted, hammered, distressed, live edge, woven
  color    — a colour or a finish tone: black, white, walnut, oak (as a tone),
             sage, cream, grey, espresso. Any colour word is `color`, and
             never `style`.
  size     — a dimension or a count: oversized, 70 inch, 3 drawer, king, full
             size, extra wide, compact, narrow. A bare number with a unit is a
             size; the *thing* being counted is not (`3 drawer` is size,
             `drawers` is form).
  form     — the shape or the structure of the piece, including what parts it is
             built out of: arched, round, l shaped, corner, sectional, shaped,
             low profile, drawers, doors, shelves, legs, tiered, nested,
             floating, wall mounted, freestanding. This is the kind most often
             lost to `other` — a structural noun describing the object's form is
             `form`, not `other`.
  feature  — what it does, a mechanism or an added function: lift top, charging
             station, adjustable shelf, reclining, swivel, extendable, storage,
             cover, cushion
  style    — a named look and nothing else: japandi, mid century, farmhouse,
             boho, industrial, scandinavian. Not a catch-all — if the term is a
             colour, a surface treatment or a material, it is one of those.
  room     — where the piece goes or what it is used with, the setting: living
             room, bedroom, bathroom, garage, entryway, kitchen, patio, office,
             nursery, outdoor, tv, desk, dining. A room name or a use-setting is
             `room`, never `other`.
  other    — a genuine design attribute that none of the nine above can hold.
             Expect this to be rare. If you cannot name which decision the term
             belongs to, prefer `drop`.
Drop a term that is not a design attribute at all: a shipping promise, a
warranty, a marketing adjective, a bare number, a category noun."""



# ------------------------------------------------------------ combinations ----
# A single element is an alternative, not a product. "Fluted" is a decision; a
# brief is "a black solid-wood fluted sideboard for a bedroom". So the terms get
# recombined into the specs the market has actually built, and those are what
# gets plotted.

# Attributes below this many on one listing are not a combination, they are the
# element chart again.
MIN_COMBO_ATTRS = 2
# Listings carrying the exact spec, below which it is one seller's idea rather
# than a pattern. Higher than the single-term bar: a spec is a narrower claim, so
# three coincidences prove less than three do for one word.
MIN_COMBO_ASINS = 4
# How many specs are worth putting on one chart.
MAX_COMBOS = 60
# Attributes in one spec label. Past four the label is a sentence and the point
# is unreadable; the hover card carries the rest.
MAX_COMBO_ATTRS = 4


def combinations(products: Sequence[Mapping[str, Any]],
                 named: Sequence[Mapping[str, Any]],
                 keywords: Sequence[Mapping[str, Any]] = (),
                 *, previous: Sequence[Mapping[str, Any]] = ()) -> list[dict]:
    """The specs the market has built, each measured on both halves.

    Every spec here came off a real listing. Enumerating the cartesian product of
    the mined vocabulary would produce thousands of specs, nearly all of which
    nobody has ever made — and a chart of hypothetical products with a measured
    axis is a chart that invites you to read noise as an opening. So the
    signature is read *off* each listing: which attributes does this title name,
    and with which words.

    Demand is the strict reading: a phrase has to carry every term in the spec.
    Most specs will have no phrase at all, and that is the honest answer —
    "nobody searches for this exact combination" is different from "we blended
    the growth of its parts", which would be a number we made up.
    """
    kinds = {row["term"]: row["kind"] for row in named
             if row.get("kind") and row["kind"] != OTHER}
    labels = {row["term"]: row.get("label") or row["term"] for row in named}
    kind_labels = {row["term"]: row.get("kind_label") or row["kind"] for row in named}
    # Rank inside a kind, so a title naming two materials picks the same one
    # every month rather than whichever the tokeniser happened to emit first.
    rank = {row["term"]: -(row.get("revenue_share_pct") or 0.0) for row in named}
    if not kinds:
        return []

    total_revenue = sum((_num(p.get("revenue")) or 0.0) for p in products)
    specs: dict[tuple[str, ...], dict] = {}
    for product in products:
        title = str(product.get("title") or "")
        if not title:
            continue
        present = [t for t in _terms(_tokens(title)) if t in kinds]
        if not present:
            continue
        # One term per attribute: a spec says "the material is oak", not "the
        # materials are oak and walnut".
        best: dict[str, str] = {}
        for term in sorted(present, key=lambda t: (rank[t], t)):
            best.setdefault(kinds[term], term)
        if len(best) < MIN_COMBO_ATTRS:
            continue
        signature = tuple(best[k] for k in KIND_ORDER if k in best)
        bucket = specs.setdefault(signature, {
            "asins": 0, "revenue": 0.0, "_prices": [], "_ratings": [],
            "_reviews": []})
        bucket["asins"] += 1
        revenue = _num(product.get("revenue")) or 0.0
        bucket["revenue"] += revenue
        price = _num(product.get("price"))
        if price is not None:
            bucket["_prices"].append(price)
        # Weighted by revenue: the rating a shopper meets is the one carried by
        # the listings that actually sell, not the average of every listing that
        # happens to name the spec.
        rating = _num(product.get("rating"))
        if rating is not None and rating > 0:
            bucket["_ratings"].append((rating, revenue))
        reviews = _num(product.get("ratings"))
        if reviews is not None and reviews >= 0:
            bucket["_reviews"].append(reviews)

    kept = {sig: agg for sig, agg in specs.items()
            if agg["asins"] >= MIN_COMBO_ASINS}
    demand = _combo_demand(kept, keywords, previous)

    out: list[dict] = []
    for signature, agg in kept.items():
        want = demand.get(signature) or {}
        prices = agg["_prices"]
        rating, rated_asins = _weighted_rating(agg["_ratings"])
        shown = signature[:MAX_COMBO_ATTRS]
        out.append({
            "key": "+".join(signature),
            "terms": list(signature),
            # The spec broken out attribute by attribute, for the hover card:
            # "材质 实木 · 颜色 黑色" reads; a glued string does not.
            "spec": [{"kind": kinds[t], "kind_label": kind_labels[t],
                      "label": labels[t]} for t in signature],
            "label": " · ".join(labels[t] for t in shown),
            "attrs": len(signature),
            "asins": agg["asins"],
            "revenue": round(agg["revenue"], 2),
            "revenue_share_pct": (round(agg["revenue"] / total_revenue * 100.0, 1)
                                  if total_revenue > 0 else 0.0),
            "avg_price": round(sum(prices) / len(prices), 2) if prices else None,
            # How well the market does this spec, and what it costs to be
            # believed in it. Both come off the same listing rows the shelf
            # share does, so they are readable for every spec on the chart
            # rather than for the handful that a search phrase happens to name.
            "rating": rating,
            "rated_asins": rated_asins,
            "reviews": _median_int(agg["_reviews"]),
            "shelf_rated": True,
            "searches": int(want.get("searches") or 0),
            "keyword_count": int(want.get("keyword_count") or 0),
            "growth_pct": want.get("growth_pct"),
            "window": want.get("window") or "",
            "keywords": want.get("keywords") or [],
            "rated": bool(want.get("rated")),
        })
    out.sort(key=lambda c: (c["revenue_share_pct"], c["asins"]), reverse=True)
    return out[:MAX_COMBOS]


def _weighted_rating(rows: Sequence[tuple[float, float]]) -> tuple[float | None, int]:
    """Revenue-weighted star rating for a spec, and how many listings carried one.

    Falls back to the plain mean when none of the rated listings has a revenue
    estimate: a rating observed on every listing is still worth stating, and
    dropping it would hand the chart back the blank axis it just got rid of.
    """
    if not rows:
        return None, 0
    weight = sum(w for _, w in rows)
    if weight > 0:
        return round(sum(r * w for r, w in rows) / weight, 2), len(rows)
    return round(sum(r for r, _ in rows) / len(rows), 2), len(rows)


def _median_int(values: Sequence[float]) -> int | None:
    """Median review count — the entry bar, in the unit a listing reports it."""
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    value = (ordered[mid] if len(ordered) % 2
             else (ordered[mid - 1] + ordered[mid]) / 2)
    return int(round(value))


def _combo_demand(specs: Mapping[tuple[str, ...], Any],
                  keywords: Sequence[Mapping[str, Any]],
                  previous: Sequence[Mapping[str, Any]]) -> dict[tuple[str, ...], dict]:
    """Phrases that carry every term of a spec, aggregated per spec.

    Quadratic in principle — every phrase against every spec — but both sides are
    small after their own filters (a few hundred phrases, a few dozen specs), and
    the inner test is a subset check on a prepared set.
    """
    before = {str(r.get("keyword") or ""): _num(r.get("searches")) or 0.0
              for r in previous}
    phrases = []
    for row in keywords:
        phrase = str(row.get("keyword") or "").strip()
        if not phrase:
            continue
        growth, window = _growth_of(row, before)
        phrases.append((_terms(_tokens(phrase)), phrase,
                        _num(row.get("searches")) or 0.0, growth, window))

    buckets: dict[tuple[str, ...], dict] = {}
    for signature in specs:
        needed = set(signature)
        bucket = {"searches": 0.0, "keyword_count": 0, "keywords": [],
                  "_weighted": 0.0, "_weight": 0.0, "_windows": {}}
        for terms, phrase, searches, growth, window in phrases:
            if not needed <= terms:
                continue
            bucket["searches"] += searches
            bucket["keyword_count"] += 1
            bucket["keywords"].append({"keyword": phrase, "searches": searches,
                                       "growth_pct": growth})
            if growth is not None and searches > 0:
                bucket["_weighted"] += growth * searches
                bucket["_weight"] += searches
                bucket["_windows"][window] = (
                    bucket["_windows"].get(window, 0.0) + searches)
        if not bucket["keyword_count"]:
            continue
        weight = bucket.pop("_weight")
        weighted = bucket.pop("_weighted")
        windows = bucket.pop("_windows")
        bucket["growth_pct"] = round(weighted / weight, 1) if weight else None
        bucket["window"] = max(windows, key=windows.get) if windows else ""
        bucket["keywords"] = sorted(bucket["keywords"],
                                    key=lambda k: k["searches"], reverse=True)[:5]
        bucket["searches"] = round(bucket["searches"])
        # A spec is a narrower claim than a word, so one phrase carrying all of
        # it is evidence where one phrase carrying a single term was not.
        bucket["rated"] = bool(bucket["growth_pct"] is not None
                               and bucket["searches"] >= MIN_SEARCHES)
        buckets[signature] = bucket
    return buckets


# ------------------------------------------------- specs on a single shelf ----
# `combinations` reads the department as one shelf: "black fluted" is one point
# wherever it was built. That answers "what is this department doing", and it is
# the wrong unit for the question a roadmap is written from. Fluted in
# Nightstands and fluted in Sofas are different factories, different competitors
# and different money, and averaging them hides the one node where the look is
# still open.
#
# So the titles are read a second time with the node kept, and a point becomes
# the four things a brief actually names: the room, the shelf, the colour and
# the look.

# What counts as a look. The word the brief uses is 外观元素 — a surface
# treatment, a named style, a silhouette or a material: burl, mid century,
# distressed, wavy, glass. Sizes, mechanisms and rooms are real decisions too
# and they are not what the piece looks like; folding them in here would put
# "12 inch" next to "burl" as though a buyer chose between them.
#
# Order is priority, because one slot holds one look: the more specific decision
# wins. A material is last precisely because nearly every title names one, so
# taking it first would fill the chart with "oak" and hide every surface
# treatment behind it.
LOOK_KINDS: tuple[str, ...] = (CRAFT, STYLE, FORM, MATERIAL)
_SPEC_KINDS: frozenset[str] = frozenset((COLOR,) + LOOK_KINDS)

# A cell of the category × colour × look grid below this many listings is one
# seller's idea rather than something the shelf does. Higher than
# ``MIN_COMBO_ASINS`` because this cell is narrower: it is a spec *and* a node.
#
# It is the only bar here. Every cell that clears it is measured and returned;
# which of them a chart has room for is the panel's decision, and keeping that
# decision out of this module is what lets the count beside the chart say how
# many specs the shelf actually has rather than how many survived a cap.
MIN_SPEC_ASINS = 5
# Whose share "可进入度" is measured against. Top *five* is the node-level
# figure the vendor publishes and it is degenerate at this grain: a spec carried
# by six listings has five brands inside its top five whatever the shelf looks
# like.
TOP_BRANDS = 3


def category_specs(products: Sequence[Mapping[str, Any]],
                   named: Sequence[Mapping[str, Any]],
                   nodes: Mapping[str, Any],
                   *, before: Sequence[Mapping[str, Any]] = ()) -> list[dict]:
    """Room × shelf × colour × look, measured on the listings that carry it.

    Every cell came off real titles inside one node. Enumerating the catalog
    against the vocabulary would produce tens of thousands of products nobody
    has built, each with a measured-looking position — the same objection that
    keeps :func:`combinations` reading signatures off listings rather than
    multiplying term lists together.

    Two numbers per cell, both read off the same rows:

    * **可进入度** — what is left after the three largest brands inside the cell.
      A look three brands own is not open to a fourth however fast it is
      growing, and that is a different fact from the node's own concentration:
      a crowded category can hold a wide-open corner.
    * **份额变化** — how much of its node's head revenue the cell holds now
      against last month, in percentage points. Deliberately a share and not a
      growth rate: the number of listings we hold for a node moves with what the
      monthly walk managed to collect, so absolute revenue is part measurement
      and part collection artefact, while a share is not. It also strips out the
      category's own tide, which is what leaves the look's own movement.

    A node with nothing stored for the comparison month has no share to move
    against, and its cells come back with ``share_shift_pp`` unset — for the
    chart to rail rather than draw at zero.
    """
    kinds = {row["term"]: row["kind"] for row in named
             if row.get("kind") in _SPEC_KINDS}
    if not kinds or not nodes:
        return []
    labels = {row["term"]: row.get("label") or row["term"] for row in named}
    kind_labels = {row["term"]: row.get("kind_label") or row["kind"] for row in named}
    # Rank inside a kind, so a title naming two colours picks the same one every
    # month rather than whichever the tokeniser happened to emit first.
    rank = {row["term"]: -(row.get("revenue_share_pct") or 0.0) for row in named}

    cells, totals = _shelf_cells(products, kinds, rank, nodes)
    prior, prior_totals = _shelf_cells(before, kinds, rank, nodes)

    out: list[dict] = []
    for (node, colour, look), agg in cells.items():
        if agg["asins"] < MIN_SPEC_ASINS or agg["revenue"] <= 0:
            continue
        total = totals.get(node) or 0.0
        share = agg["revenue"] / total * 100.0 if total > 0 else 0.0
        # Absent last month is a measured zero, as long as the node itself was
        # collected — a look that did not exist and now holds 3% of the shelf is
        # the most interesting row on this chart, and dropping it for having no
        # predecessor would delete exactly the specs worth finding.
        before_total = prior_totals.get(node) or 0.0
        if before_total > 0:
            was = ((prior.get((node, colour, look)) or {}).get("revenue") or 0.0)
            share_before = was / before_total * 100.0
            shift = round(share - share_before, 2)
        else:
            share_before, shift = None, None
        rating, _rated = _weighted_rating(agg["_ratings"])
        prices = agg["_prices"]
        terms = [t for t in (colour, look) if t]
        out.append({
            "key": "|".join((node, colour, look)),
            "node_key": node,
            # The spec broken out row by row for the hover card. The two
            # category rows are added by the panel, which is where the node's
            # own labels live — a look is only open or crowded *somewhere*.
            "spec": [{"kind": kinds[t], "kind_label": kind_labels[t],
                      "label": labels[t]} for t in terms],
            "color": labels.get(colour) if colour else None,
            "look": labels.get(look) if look else None,
            "asins": agg["asins"],
            "revenue": round(agg["revenue"], 2),
            "share_pct": round(share, 2),
            "share_before_pct": (round(share_before, 2)
                                 if share_before is not None else None),
            "share_shift_pp": shift,
            "entry": _entry_score(agg),
            "brands": len(agg["_brands"]),
            "avg_price": round(sum(prices) / len(prices), 2) if prices else None,
            "rating": rating,
            "reviews": _median_int(agg["_reviews"]),
        })

    # Biggest first: the money is the reading, and it is also the order the
    # panel spends its plot budget in.
    out.sort(key=lambda s: s["revenue"], reverse=True)
    return out


def _shelf_cells(products: Sequence[Mapping[str, Any]],
                 kinds: Mapping[str, str],
                 rank: Mapping[str, float],
                 nodes: Mapping[str, Any],
                 ) -> tuple[dict[tuple[str, str, str], dict], dict[str, float]]:
    """Listings grouped into (node, colour, look), with each node's own total.

    The total counts every listing in the node, including the ones naming
    neither a colour nor a look: it is the denominator the shares are of, and
    leaving the unnamed listings out of it would inflate every cell by however
    much of the shelf writes plain titles.
    """
    cells: dict[tuple[str, str, str], dict] = {}
    totals: dict[str, float] = {}
    for product in products:
        node = str(product.get("node_id_path") or "")
        if node not in nodes:
            continue
        revenue = _num(product.get("revenue")) or 0.0
        totals[node] = totals.get(node, 0.0) + revenue
        title = str(product.get("title") or "")
        if not title:
            continue
        best: dict[str, str] = {}
        present = [t for t in _terms(_tokens(title)) if t in kinds]
        for term in sorted(present, key=lambda t: (rank.get(t, 0.0), t)):
            best.setdefault(kinds[term], term)
        colour = best.get(COLOR, "")
        look = next((best[kind] for kind in LOOK_KINDS if kind in best), "")
        if not colour and not look:
            continue
        cell = cells.setdefault((node, colour, look), {
            "asins": 0, "revenue": 0.0, "_prices": [], "_ratings": [],
            "_reviews": [], "_brands": {}})
        cell["asins"] += 1
        cell["revenue"] += revenue
        # An unrecorded brand is not evidence that one brand owns the cell, so
        # each such listing counts as its own owner. The conservative direction:
        # missing data can leave a cell looking open, never crowded.
        brand = str(product.get("brand") or "").strip().lower()
        owner = brand or f"·{product.get('asin') or len(cell['_brands'])}"
        cell["_brands"][owner] = cell["_brands"].get(owner, 0.0) + revenue
        price = _num(product.get("price"))
        if price is not None:
            cell["_prices"].append(price)
        rating = _num(product.get("rating"))
        if rating is not None and rating > 0:
            cell["_ratings"].append((rating, revenue))
        reviews = _num(product.get("ratings"))
        if reviews is not None and reviews >= 0:
            cell["_reviews"].append(reviews)
    return cells, totals


def _entry_score(cell: Mapping[str, Any]) -> float:
    """What is left of a cell once its three largest brands have taken theirs.

    100 is a look nobody owns; 0 is one three brands hold outright. The same
    reading as the board's 可进入度, which is ``100 - top5_brand_crn``, at the
    grain where the decision is made.
    """
    revenue = cell["revenue"]
    if revenue <= 0:
        return 0.0
    top = sorted(cell["_brands"].values(), reverse=True)[:TOP_BRANDS]
    return round(max(0.0, 100.0 - sum(top) / revenue * 100.0), 1)


def naming_brief(terms: Sequence[dict]) -> str:
    """The mined terms as the model receives them, for naming only."""
    lines = [_KIND_RULES, "",
             "MINED DESIGN TERMS (discovered from listing titles and search phrases; "
             "the numbers are final — classify and name, never evaluate):",
             "term | head ASINs | revenue share | monthly searches"]
    for row in terms:
        lines.append(f"{row['term']} | {row['asins']} | {row['revenue_share_pct']}% | "
                     f"{row['searches']:,}")
    return "\n".join(lines)


def brief(rising: Sequence[dict], falling: Sequence[dict], zh: bool) -> str:
    """The element read, as the model receives it. Names only; no new numbers."""
    if not rising and not falling:
        return ""
    lines = ["ELEMENT DEMAND (search-weighted, computed server-side — do not restate "
             "the percentages, cite the keyword evidence instead):"]
    for row in rising:
        lines.append(f"  RISING {row.get('label') or row['term']} "
                     f"({row.get('kind', '')}) {row['growth_pct']:+.1f}% over "
                     f"{row['keyword_count']} phrases, {row['searches']:,} searches")
    for row in falling:
        lines.append(f"  FALLING {row.get('label') or row['term']} "
                     f"({row.get('kind', '')}) {row['growth_pct']:+.1f}% over "
                     f"{row['keyword_count']} phrases, {row['searches']:,} searches")
    return "\n".join(lines)
