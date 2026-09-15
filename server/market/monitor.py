"""Risk and opportunity monitoring: deterministic signals over the warehouse.

The board answers "where should we look"; the deep dive answers "what is going on
here". Neither answers **"what changed, and is it moving for or against us"** —
that is this module. It reads the same rows everything else reads and turns them
into a ranked list of alerts.

Three rules that make the alerts worth reading:

* **No model involvement.** Every threshold below is arithmetic on stored columns.
  A model asked to spot "worrying trends" produces them at a steady rate whether
  or not any exist; a model handed a finished list can only summarise it.
* **Every alert cites its evidence.** ``evidence_metrics`` names the snapshot
  columns behind the number and the caller resolves them to ``ev_`` ids, so an
  alert opens the same drawer a KPI does.
* **A missing input fires nothing** — not a low-severity alert, not a warning.
  An alert that means "we have no data" teaches people to ignore alerts.

Signals come in pairs wherever the data allows (``return_above_peers`` /
``return_below_peers``), because the same column read the other way round is
often the stronger finding: for freight-shipped furniture a return rate well
under the neighbourhood average is worth more than most growth.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Sequence

from .scoring import _median, _num

HIGH, MEDIUM, LOW = "high", "medium", "low"
RISK, OPPORTUNITY = "risk", "opportunity"
_SEVERITY_RANK = {HIGH: 3, MEDIUM: 2, LOW: 1}

# How many months of history a trend signal needs before it may speak.
MIN_TREND_POINTS = 3
MAX_ALERTS_PER_NODE = 8
MAX_OVERVIEW_ALERTS = 12
# How many nodes one signal may occupy on the board before the rest of its
# hits are demoted behind the distinct findings.
MAX_PER_SIGNAL = 3


@dataclass(frozen=True)
class NodeFacts:
    """Everything the signals may look at, for one node.

    A dataclass rather than a pile of keyword arguments so a test can build a
    node out of literals and run the whole signal set with no database, no
    vendor and no model.
    """

    node_key: str
    label: str = ""
    snapshot: Mapping[str, Any] = field(default_factory=dict)
    # Ascending by period and *including* the current one, the way
    # store.snapshot_history returns it: the signals index from the end.
    history: Sequence[Mapping[str, Any]] = ()
    keywords: Sequence[Mapping[str, Any]] = ()
    products: Sequence[Mapping[str, Any]] = ()
    themes: Sequence[Mapping[str, Any]] = ()
    distributions: Mapping[str, Sequence[Mapping[str, Any]]] = field(default_factory=dict)
    concentration: Mapping[str, Sequence[Mapping[str, Any]]] = field(default_factory=dict)
    trend_index: Sequence[Mapping[str, Any]] = ()
    # Department medians, so a node is read against its siblings rather than
    # against a constant somebody picked once.
    peers: Mapping[str, float | None] = field(default_factory=dict)


@dataclass(frozen=True)
class Alert:
    id: str
    kind: str
    family: str
    severity: str
    magnitude: float
    metric: str
    value: float | None = None
    baseline: float | None = None
    delta: float | None = None
    unit: str = ""
    evidence_metrics: tuple[str, ...] = ()
    extra: Mapping[str, Any] = field(default_factory=dict)


Signal = Callable[[NodeFacts], "Alert | None"]


# ------------------------------------------------------------------ helpers ----

def _snap(facts: NodeFacts, key: str) -> float | None:
    return _num(facts.snapshot.get(key))


def _series(facts: NodeFacts, key: str) -> list[float]:
    """One column's history, oldest first, missing months dropped.

    Dropped rather than zero-filled: a month the sweep never reached is not a
    month the category sold nothing, and a zero reads as a collapse.
    """
    out: list[float] = []
    for row in facts.history:
        value = _num(row.get(key))
        if value is not None:
            out.append(value)
    return out


def _baseline(facts: NodeFacts, key: str, window: int = 3) -> float | None:
    """Mean of the ``window`` months *before* the current one.

    One previous month is too noisy to raise an alert on — a restock, a Prime
    Day — so trend signals compare against a short trailing mean instead.
    """
    series = _series(facts, key)
    if len(series) < MIN_TREND_POINTS:
        return None
    prior = series[:-1][-window:]
    return sum(prior) / len(prior) if prior else None


def _rel(value: float | None, base: float | None) -> float | None:
    """Relative change in percent; ``None`` unless both sides are usable."""
    if value is None or base is None or base == 0:
        return None
    return (value - base) / abs(base) * 100.0


def _pp(value: float | None, base: float | None) -> float | None:
    """Change in percentage points between two fractions."""
    if value is None or base is None:
        return None
    return (value - base) * 100.0


def _pct(value: float | None) -> float | None:
    return None if value is None else value * 100.0


def _by(table: Sequence[tuple[float, str]], value: float) -> str | None:
    """First threshold the value clears, read as ``>=``. ``None`` = no alert."""
    for threshold, severity in table:
        if value >= threshold:
            return severity
    return None


def _mean(values: Sequence[float | None]) -> float | None:
    clean = [v for v in values if v is not None]
    return sum(clean) / len(clean) if clean else None


# ------------------------------------------------------------------ signals ----
# Each returns an Alert or None. They are deliberately flat and repetitive: a
# signal whose arithmetic needs explaining is a signal nobody trusts when it
# fires.

def return_above_peers(facts: NodeFacts) -> Alert | None:
    rate, peer = _snap(facts, "return_ratio"), _snap(facts, "return_ratio_avg")
    if rate is None or not peer:
        return None
    multiple = rate / peer
    severity = _by(((1.5, HIGH), (1.25, MEDIUM), (1.1, LOW)), multiple)
    if severity is None:
        return None
    return Alert(
        id="return_above_peers", kind=RISK, family="return", severity=severity,
        magnitude=min(100.0, (multiple - 1.0) * 120.0), metric="return_ratio",
        value=_pct(rate), baseline=_pct(peer), delta=_pp(rate, peer), unit="%",
        evidence_metrics=("return_ratio", "return_ratio_avg"),
        extra={"multiple": round(multiple, 2)},
    )


def return_below_peers(facts: NodeFacts) -> Alert | None:
    """The inverse, and for freight furniture the more valuable half.

    A return on a 70kg sideboard costs more than the order's margin, so a
    category returning a third less than its neighbours is structurally cheaper
    to serve — an advantage that appears nowhere in the revenue figures.
    """
    rate, peer = _snap(facts, "return_ratio"), _snap(facts, "return_ratio_avg")
    if rate is None or not peer:
        return None
    multiple = rate / peer
    severity = _by(((0.35, HIGH), (0.2, MEDIUM), (0.1, LOW)), 1.0 - multiple)
    if severity is None:
        return None
    return Alert(
        id="return_below_peers", kind=OPPORTUNITY, family="return", severity=severity,
        magnitude=min(100.0, (1.0 - multiple) * 200.0), metric="return_ratio",
        value=_pct(rate), baseline=_pct(peer), delta=_pp(rate, peer), unit="%",
        evidence_metrics=("return_ratio", "return_ratio_avg"),
        extra={"multiple": round(multiple, 2)},
    )


def return_rising(facts: NodeFacts) -> Alert | None:
    rate, base = _snap(facts, "return_ratio"), _baseline(facts, "return_ratio")
    change = _rel(rate, base)
    if change is None:
        return None
    severity = _by(((30.0, HIGH), (18.0, MEDIUM), (10.0, LOW)), change)
    if severity is None:
        return None
    return Alert(
        id="return_rising", kind=RISK, family="return", severity=severity,
        magnitude=min(100.0, change * 2.0), metric="return_ratio",
        value=_pct(rate), baseline=_pct(base), delta=_pp(rate, base), unit="%",
        evidence_metrics=("return_ratio",),
    )


def demand_falling(facts: NodeFacts) -> Alert | None:
    revenue, base = _snap(facts, "total_revenue"), _baseline(facts, "total_revenue")
    change = _rel(revenue, base)
    if change is None or change >= 0:
        return None
    drop = -change
    severity = _by(((20.0, HIGH), (10.0, MEDIUM), (5.0, LOW)), drop)
    if severity is None:
        return None
    return Alert(
        id="demand_falling", kind=RISK, family="demand", severity=severity,
        magnitude=min(100.0, drop * 3.0), metric="total_revenue",
        value=revenue, baseline=base, delta=change, unit="$",
        evidence_metrics=("total_revenue",),
    )


def demand_accelerating(facts: NodeFacts) -> Alert | None:
    """Growing, and growing faster than the department — the second half matters.

    In a month when every furniture category is up 12%, a category up 12% is not
    an opportunity, it is the weather.
    """
    revenue, base = _snap(facts, "total_revenue"), _baseline(facts, "total_revenue")
    change = _rel(revenue, base)
    if change is None or change <= 0:
        return None
    peer = facts.peers.get("revenue_growth_pct")
    if peer is not None and change <= peer:
        return None
    severity = _by(((25.0, HIGH), (12.0, MEDIUM), (6.0, LOW)), change)
    if severity is None:
        return None
    return Alert(
        id="demand_accelerating", kind=OPPORTUNITY, family="demand", severity=severity,
        magnitude=min(100.0, change * 2.5), metric="total_revenue",
        value=revenue, baseline=base, delta=change, unit="$",
        evidence_metrics=("total_revenue",), extra={"peer_growth_pct": peer},
    )


def price_erosion(facts: NodeFacts) -> Alert | None:
    price, base = _snap(facts, "avg_price"), _baseline(facts, "avg_price")
    change = _rel(price, base)
    if change is None or change >= 0:
        return None
    drop = -change
    severity = _by(((12.0, HIGH), (7.0, MEDIUM), (4.0, LOW)), drop)
    if severity is None:
        return None
    return Alert(
        id="price_erosion", kind=RISK, family="pricing", severity=severity,
        magnitude=min(100.0, drop * 5.0), metric="avg_price",
        value=price, baseline=base, delta=change, unit="$",
        evidence_metrics=("avg_price",),
    )


def consolidating(facts: NodeFacts) -> Alert | None:
    share, base = _snap(facts, "top5_brand_crn"), _baseline(facts, "top5_brand_crn")
    delta = _pp(share, base)
    if delta is None or delta <= 0:
        return None
    severity = _by(((6.0, HIGH), (3.5, MEDIUM), (2.0, LOW)), delta)
    if severity is None:
        return None
    return Alert(
        id="consolidating", kind=RISK, family="competition", severity=severity,
        magnitude=min(100.0, delta * 10.0), metric="top5_brand_crn",
        value=_pct(share), baseline=_pct(base), delta=delta, unit="pp",
        evidence_metrics=("top5_brand_crn",),
    )


def fragmenting(facts: NodeFacts) -> Alert | None:
    share, base = _snap(facts, "top5_brand_crn"), _baseline(facts, "top5_brand_crn")
    delta = _pp(share, base)
    if delta is None or delta >= 0:
        return None
    drop = -delta
    severity = _by(((5.0, HIGH), (3.0, MEDIUM), (1.5, LOW)), drop)
    if severity is None:
        return None
    return Alert(
        id="fragmenting", kind=OPPORTUNITY, family="competition", severity=severity,
        magnitude=min(100.0, drop * 12.0), metric="top5_brand_crn",
        value=_pct(share), baseline=_pct(base), delta=delta, unit="pp",
        evidence_metrics=("top5_brand_crn",),
    )


def amazon_entering(facts: NodeFacts) -> Alert | None:
    """Amazon's own share, high or rising. Either reading says slow down."""
    share = _snap(facts, "amazon_self_proportion")
    if share is None:
        return None
    base = _baseline(facts, "amazon_self_proportion")
    delta = _pp(share, base)
    severity = _by(((0.12, HIGH), (0.06, MEDIUM), (0.03, LOW)), share)
    if delta is not None and delta >= 2.0 and severity != HIGH:
        severity = HIGH if delta >= 4.0 else MEDIUM
    if severity is None:
        return None
    return Alert(
        id="amazon_entering", kind=RISK, family="competition", severity=severity,
        magnitude=min(100.0, share * 400.0), metric="amazon_self_proportion",
        value=_pct(share), baseline=_pct(base), delta=delta, unit="%",
        evidence_metrics=("amazon_self_proportion",),
    )


def supply_outpacing_demand(facts: NodeFacts) -> Alert | None:
    """Listings growing faster than revenue: the same money split more ways."""
    listings = _rel(_snap(facts, "total_products"), _baseline(facts, "total_products"))
    revenue = _rel(_snap(facts, "total_revenue"), _baseline(facts, "total_revenue"))
    if listings is None or revenue is None:
        return None
    spread = listings - revenue
    severity = _by(((18.0, HIGH), (10.0, MEDIUM), (5.0, LOW)), spread)
    if severity is None:
        return None
    return Alert(
        id="supply_outpacing_demand", kind=RISK, family="competition", severity=severity,
        magnitude=min(100.0, spread * 4.0), metric="total_products",
        value=listings, baseline=revenue, delta=spread, unit="pp",
        evidence_metrics=("total_products", "total_revenue"),
    )


def entrenchment_rising(facts: NodeFacts) -> Alert | None:
    """Head listings accumulating reviews faster than a newcomer can catch up."""
    ratings, base = _snap(facts, "hl_avg_ratings"), _baseline(facts, "hl_avg_ratings")
    change = _rel(ratings, base)
    if change is None:
        return None
    severity = _by(((25.0, HIGH), (14.0, MEDIUM), (8.0, LOW)), change)
    if severity is None:
        return None
    return Alert(
        id="entrenchment_rising", kind=RISK, family="competition", severity=severity,
        magnitude=min(100.0, change * 2.5), metric="hl_avg_ratings",
        value=ratings, baseline=base, delta=change, unit="",
        evidence_metrics=("hl_avg_ratings",),
    )


def newcomer_window_open(facts: NodeFacts) -> Alert | None:
    """New listings taking real revenue *and* doing it without a review moat."""
    from .scoring import new_revenue_share_pct

    share = new_revenue_share_pct(dict(facts.snapshot))
    if share is None:
        return None
    reviews = _snap(facts, "new_avg_reviews_l12")
    severity = _by(((20.0, HIGH), (12.0, MEDIUM), (7.0, LOW)), share)
    if severity is None:
        return None
    # A newcomer share carried by listings that already hold 2000 reviews is not
    # a window, it is a well-funded competitor. Demote rather than suppress.
    if reviews is not None and reviews > 1500 and severity != LOW:
        severity = MEDIUM if severity == HIGH else LOW
    return Alert(
        id="newcomer_window_open", kind=OPPORTUNITY, family="entry", severity=severity,
        magnitude=min(100.0, share * 4.0), metric="new_ratio_l12",
        value=share, unit="%",
        evidence_metrics=("new_count_l12", "new_ratio_l12", "new_avg_revenue_l12"),
        extra={"new_avg_reviews": reviews},
    )


def newcomer_window_closing(facts: NodeFacts) -> Alert | None:
    ratio, base = _snap(facts, "new_ratio_l12"), _baseline(facts, "new_ratio_l12")
    delta = _pp(ratio, base)
    if delta is None or delta >= 0:
        return None
    drop = -delta
    severity = _by(((5.0, HIGH), (3.0, MEDIUM), (1.5, LOW)), drop)
    if severity is None:
        return None
    return Alert(
        id="newcomer_window_closing", kind=RISK, family="entry", severity=severity,
        magnitude=min(100.0, drop * 12.0), metric="new_ratio_l12",
        value=_pct(ratio), baseline=_pct(base), delta=delta, unit="pp",
        evidence_metrics=("new_ratio_l12",),
    )


def conversion_weakening(facts: NodeFacts) -> Alert | None:
    """Search-to-purchase below the neighbourhood: traffic that does not convert."""
    rate = _snap(facts, "search_purchase_ratio")
    peer = _snap(facts, "search_purchase_ratio_avg")
    if rate is None or not peer:
        return None
    shortfall = (peer - rate) / peer * 100.0
    severity = _by(((30.0, HIGH), (18.0, MEDIUM), (10.0, LOW)), shortfall)
    if severity is None:
        return None
    return Alert(
        id="conversion_weakening", kind=RISK, family="demand", severity=severity,
        magnitude=min(100.0, shortfall * 2.0), metric="search_purchase_ratio",
        value=rate, baseline=peer, delta=-shortfall, unit="",
        evidence_metrics=("search_purchase_ratio", "search_purchase_ratio_avg"),
    )


def quality_gap(facts: NodeFacts) -> Alert | None:
    """Money in the category, ratings saying the buyers are not happy.

    The clearest design-led entry there is: demand is proven and the incumbent
    products are the reason satisfaction is low.
    """
    rating = _snap(facts, "avg_rating")
    revenue = _snap(facts, "total_revenue")
    peer_revenue = facts.peers.get("total_revenue")
    if rating is None or revenue is None:
        return None
    if peer_revenue is not None and revenue < peer_revenue:
        return None
    severity = _by(((0.45, HIGH), (0.3, MEDIUM), (0.15, LOW)), 4.4 - rating)
    if severity is None:
        return None
    return Alert(
        id="quality_gap", kind=OPPORTUNITY, family="quality", severity=severity,
        magnitude=min(100.0, (4.4 - rating) * 120.0), metric="avg_rating",
        value=rating, baseline=4.4, delta=rating - 4.4, unit="★",
        evidence_metrics=("avg_rating", "total_revenue"),
        extra={"revenue": revenue},
    )


def premium_headroom(facts: NodeFacts) -> Alert | None:
    """A price band earning a bigger share of revenue than of listings.

    That gap is the market saying it will pay more than the shelf currently asks,
    and it is the most actionable number there is for setting a target price.
    """
    best: tuple[float, Mapping[str, Any]] | None = None
    for band in facts.distributions.get("price") or ():
        revenue = _num(band.get("revenue_ratio"))
        listings = _num(band.get("products_ratio"))
        if listings is None:
            listings = _num(band.get("units_ratio"))
        if revenue is None or listings is None:
            continue
        gap = (revenue - listings) * 100.0
        if best is None or gap > best[0]:
            best = (gap, band)
    if best is None:
        return None
    gap, band = best
    severity = _by(((12.0, HIGH), (7.0, MEDIUM), (4.0, LOW)), gap)
    if severity is None:
        return None
    listing_share = _num(band.get("products_ratio"))
    if listing_share is None:
        listing_share = _num(band.get("units_ratio"))
    return Alert(
        id="premium_headroom", kind=OPPORTUNITY, family="pricing", severity=severity,
        magnitude=min(100.0, gap * 6.0), metric="price_band",
        value=_pct(_num(band.get("revenue_ratio"))), baseline=_pct(listing_share),
        delta=gap, unit="pp",
        evidence_metrics=(f"price_share_{band.get('bucket_key')}",),
        extra={"band": band.get("bucket_key")},
    )


def keyword_supply_gap(facts: NodeFacts) -> Alert | None:
    """Searched-for phrases with little competing supply behind them."""
    hits = [
        k for k in facts.keywords
        if (_num(k.get("supply_demand_ratio")) or 0) >= 12.0
        and (_num(k.get("searches")) or 0) >= 2500
    ]
    if not hits:
        return None
    severity = _by(((5.0, HIGH), (3.0, MEDIUM), (1.0, LOW)), float(len(hits)))
    if severity is None:
        return None
    top = sorted(hits, key=lambda k: _num(k.get("supply_demand_ratio")) or 0.0,
                 reverse=True)[:3]
    return Alert(
        id="keyword_supply_gap", kind=OPPORTUNITY, family="keyword", severity=severity,
        magnitude=min(100.0, len(hits) * 12.0), metric="supply_demand_ratio",
        value=float(len(hits)), unit="",
        evidence_metrics=("supply_demand_ratio",),
        extra={"keywords": [str(k.get("keyword")) for k in top],
               "top_sdr": round(_num(top[0].get("supply_demand_ratio")) or 0.0, 1)},
    )


def offamazon_leading(facts: NodeFacts) -> Alert | None:
    """Off-Amazon interest rising while Amazon revenue is not: demand arriving early."""
    points = [p for p in (_num(row.get("google_trend_index"))
                          for row in facts.trend_index) if p is not None]
    if len(points) < MIN_TREND_POINTS * 2:
        return None
    recent = sum(points[-3:]) / 3.0
    earlier = points[:-3][-3:]
    prior = sum(earlier) / len(earlier)
    change = _rel(recent, prior)
    if change is None or change <= 0:
        return None
    amazon = _rel(_snap(facts, "total_revenue"), _baseline(facts, "total_revenue"))
    if amazon is not None and amazon >= change:
        return None
    severity = _by(((30.0, HIGH), (18.0, MEDIUM), (10.0, LOW)), change)
    if severity is None:
        return None
    return Alert(
        id="offamazon_leading", kind=OPPORTUNITY, family="demand", severity=severity,
        magnitude=min(100.0, change * 2.0), metric="google_trend_index",
        value=recent, baseline=prior, delta=change, unit="",
        extra={"amazon_growth_pct": amazon},
    )


def pain_concentrated(facts: NodeFacts) -> Alert | None:
    """One design-fixable complaint holding a large share of the negative reviews."""
    fixable = [
        theme for theme in facts.themes
        if theme.get("fixable_in_design") and (_num(theme.get("share_of_negative")) or 0) > 0
    ]
    if not fixable:
        return None
    top = max(fixable, key=lambda t: _num(t.get("share_of_negative")) or 0.0)
    share = (_num(top.get("share_of_negative")) or 0.0) * 100.0
    sample = _num(top.get("sample_size")) or 0.0
    if sample < 20:
        # Under twenty negative reviews a "theme" is three people with one problem.
        return None
    severity = _by(((30.0, HIGH), (20.0, MEDIUM), (12.0, LOW)), share)
    if severity is None:
        return None
    return Alert(
        id="pain_concentrated", kind=OPPORTUNITY, family="quality", severity=severity,
        magnitude=min(100.0, share * 2.5), metric="share_of_negative",
        value=share, unit="%",
        extra={"theme": top.get("theme_label") or top.get("theme"),
               "sample_size": int(sample),
               "return_driving": bool(top.get("return_driving"))},
    )


def ad_dependence(facts: NodeFacts) -> Alert | None:
    """Entry priced in ad spend rather than reviews — a cash risk, not a time risk."""
    share = _mean([_num(p.get("ad_proportion")) for p in facts.products])
    if share is None:
        return None
    severity = _by(((0.55, HIGH), (0.45, MEDIUM), (0.35, LOW)), share)
    if severity is None:
        return None
    return Alert(
        id="ad_dependence", kind=RISK, family="traffic", severity=severity,
        magnitude=min(100.0, share * 130.0), metric="ad_proportion",
        value=_pct(share), unit="%",
        extra={"asins": len([p for p in facts.products
                             if p.get("ad_proportion") is not None])},
    )


def organic_winnable(facts: NodeFacts) -> Alert | None:
    share = _mean([_num(p.get("natural_proportion")) for p in facts.products])
    if share is None:
        return None
    severity = _by(((0.6, HIGH), (0.5, MEDIUM), (0.42, LOW)), share)
    if severity is None:
        return None
    return Alert(
        id="organic_winnable", kind=OPPORTUNITY, family="traffic", severity=severity,
        magnitude=min(100.0, share * 110.0), metric="natural_proportion",
        value=_pct(share), unit="%",
    )


# ---- product / design ----------------------------------------------------
# The signals above read a market; these read the *thing we would have to
# build*. They exist because the brief this system serves is a product
# development brief: the decision at the end is "design what, at what size, at
# what price, with which defect engineered out" — not "buy which keyword".
#
# Every one is arithmetic over columns the sweep already pays for: ``avg_weight``
# and ``avg_volume`` come back with every ``market_research`` call, ``variations``
# with every ``product_research`` row, and the review themes carry their own
# ``fixable_in_design`` flag.

# Amazon's oversize handling steps at roughly these weights, and each step moves
# what a unit may weigh before freight eats the margin. Constants, not
# inferences — which is why they live in code rather than in a prompt.
_FREIGHT_TIERS = ((150.0, HIGH), (90.0, MEDIUM), (50.0, LOW))


def freight_heavy(facts: NodeFacts) -> Alert | None:
    """The shelf's average unit is heavy enough to set the cost floor.

    Weight is the one product attribute this business cannot design around after
    the fact: it fixes the freight tier, the damage rate and the cost of a return
    at once, and it is decided at the sketch stage.
    """
    weight = _snap(facts, "avg_weight")
    if weight is None:
        return None
    severity = _by(_FREIGHT_TIERS, weight)
    if severity is None:
        return None
    return Alert(
        id="freight_heavy", kind=RISK, family="product", severity=severity,
        magnitude=min(100.0, weight / 2.0), metric="avg_weight",
        value=weight, baseline=facts.peers.get("avg_weight"), unit="lb",
        evidence_metrics=("avg_weight", "avg_volume"),
        extra={"volume": _fmt(_snap(facts, "avg_volume"), "")},
    )


def variation_depth_expected(facts: NodeFacts) -> Alert | None:
    """Incumbents sell a range, so a single SKU enters under-equipped.

    Variation count is a product-programme fact, not a marketing one: it decides
    how many colourways and sizes tooling has to cover before launch.

    Judged against the department rather than against a number somebody picked.
    "Four variants is a lot" is only true relative to what the rest of the shelf
    does — in a category where everyone ships eight it is a thin range, and the
    absolute threshold this used to carry said the opposite.
    """
    counts = [c for c in (_num(p.get("variations")) for p in facts.products)
              if c is not None]
    depth = _median(counts)
    if depth is None:
        return None
    peer = facts.peers.get("variations")
    if peer:
        severity = _by(((1.5, HIGH), (1.25, MEDIUM), (1.1, LOW)), depth / peer)
    else:
        # No department reading yet — say nothing rather than fall back to a
        # number that would be a guess wearing a threshold's clothes.
        return None
    if severity is None:
        return None
    return Alert(
        id="variation_depth_expected", kind=RISK, family="product", severity=severity,
        magnitude=min(100.0, depth / peer * 40.0), metric="variations",
        value=depth, baseline=peer, unit="", extra={"asins": len(counts)},
    )


def _theme_share(facts: NodeFacts, predicate) -> tuple[float, list[str], int] | None:
    """Combined share of the negative sample across themes matching ``predicate``.

    Shares are summed rather than maxed because the question a design review asks
    is "how much of the complaint volume can we engineer away in total", and the
    classifier puts each review under exactly one theme.
    """
    hits = [t for t in facts.themes if predicate(t)]
    if not hits:
        return None
    sample = max((_num(t.get("sample_size")) or 0.0) for t in hits)
    if sample < 20:
        # Under twenty negative reviews a "theme" is three people with one problem.
        return None
    share = sum((_num(t.get("share_of_negative")) or 0.0) for t in hits) * 100.0
    ordered = sorted(hits, key=lambda t: _num(t.get("share_of_negative")) or 0.0,
                     reverse=True)
    names = [str(t.get("theme_label") or t.get("theme") or "") for t in ordered[:3]]
    return min(share, 100.0), [n for n in names if n], int(sample)


def design_fixable_share(facts: NodeFacts) -> Alert | None:
    """How much of the complaint volume is a design problem rather than a service one.

    The single number that decides whether a category deserves a product
    programme at all: complaints about couriers and customer service are somebody
    else's to fix, a wobbling joint is ours.
    """
    found = _theme_share(facts, lambda t: bool(t.get("fixable_in_design")))
    if found is None:
        return None
    share, names, sample = found
    severity = _by(((60.0, HIGH), (45.0, MEDIUM), (30.0, LOW)), share)
    if severity is None:
        return None
    return Alert(
        id="design_fixable_share", kind=OPPORTUNITY, family="product", severity=severity,
        magnitude=min(100.0, share * 1.4), metric="share_of_negative",
        value=share, unit="%", extra={"themes": names, "sample_size": sample},
    )


_ASSEMBLY = frozenset({"assembly_difficulty", "missing_or_wrong_parts", "instructions"})
_TRANSIT = frozenset({"damage_in_transit"})


def assembly_burden(facts: NodeFacts) -> Alert | None:
    """Flat-pack assembly is what buyers complain about; it is also cheap to fix.

    Hardware, dowel tolerance and an instruction sheet are the least expensive
    changes in the whole bill of materials, which makes this the best
    return-on-effort finding the review sample can produce.
    """
    found = _theme_share(facts, lambda t: t.get("category") in _ASSEMBLY)
    if found is None:
        return None
    share, names, sample = found
    severity = _by(((25.0, HIGH), (15.0, MEDIUM), (8.0, LOW)), share)
    if severity is None:
        return None
    return Alert(
        id="assembly_burden", kind=OPPORTUNITY, family="product", severity=severity,
        magnitude=min(100.0, share * 3.0), metric="share_of_negative",
        value=share, unit="%", extra={"themes": names, "sample_size": sample},
    )


def transit_damage_load(facts: NodeFacts) -> Alert | None:
    """Damage in transit: a packaging brief, and a return this brand pays twice for.

    Paired with ``freight_heavy`` on purpose — a heavy category that also arrives
    broken is the combination that turns a good margin negative.
    """
    found = _theme_share(facts, lambda t: t.get("category") in _TRANSIT)
    if found is None:
        return None
    share, names, sample = found
    severity = _by(((20.0, HIGH), (12.0, MEDIUM), (6.0, LOW)), share)
    if severity is None:
        return None
    return Alert(
        id="transit_damage_load", kind=RISK, family="product", severity=severity,
        magnitude=min(100.0, share * 3.5), metric="share_of_negative",
        value=share, unit="%", evidence_metrics=("avg_weight",),
        extra={"themes": names, "sample_size": sample,
               "weight": _fmt(_snap(facts, "avg_weight"), "")},
    )


# --------------------------------------------------------------- pulse layer ----
# A pulse is a live reading taken while the month is still open, compared
# like-for-like against the last month the vendor closed. It cannot see revenue
# or returns — those are aggregates and they do not exist yet — so these signals
# stay strictly inside what the live tool actually reports, and they are labelled
# as an early read rather than a result.

# (metric, id, unit, thresholds for a rise, thresholds for a fall, kind-when-up)
_PULSE_SPECS: tuple[tuple[str, str, str, tuple, tuple, str], ...] = (
    ("avg_revenue", "pulse_runrate", "$",
     ((20.0, HIGH), (10.0, MEDIUM), (5.0, LOW)),
     ((20.0, HIGH), (10.0, MEDIUM), (5.0, LOW)), OPPORTUNITY),
    ("avg_price", "pulse_price", "$",
     ((8.0, MEDIUM), (4.0, LOW)),
     ((10.0, HIGH), (6.0, MEDIUM), (3.0, LOW)), OPPORTUNITY),
    ("hl_avg_ratings", "pulse_reviewwall", "",
     ((12.0, HIGH), (6.0, MEDIUM), (3.0, LOW)), (), RISK),
    ("sellers", "pulse_sellers", "",
     ((12.0, HIGH), (6.0, MEDIUM), (3.0, LOW)), (), RISK),
    ("new_product_proportion", "pulse_newcomers", "%",
     ((20.0, MEDIUM), (10.0, LOW)),
     ((25.0, MEDIUM), (12.0, LOW)), OPPORTUNITY),
    ("avg_rating", "pulse_rating", "★",
     (), ((3.0, HIGH), (1.5, MEDIUM), (0.8, LOW)), OPPORTUNITY),
)

# Which direction is bad, per metric, when the spec's "up" kind is stated.
_PULSE_FAMILY = {
    "pulse_runrate": "demand", "pulse_price": "pricing",
    "pulse_reviewwall": "competition", "pulse_sellers": "competition",
    "pulse_newcomers": "entry", "pulse_rating": "quality",
}


def scan_pulse(pulse: Mapping[str, Any], baseline: Mapping[str, Any]) -> list[Alert]:
    """Compare a live reading against the last closed month, metric by metric.

    Deliberately not part of ``scan``: those signals describe a finished month
    and this one describes a month in flight. Mixing them would let an early
    read outrank a settled fact in the same list.
    """
    fired: list[Alert] = []
    for metric, signal_id, unit, up_table, down_table, up_kind in _PULSE_SPECS:
        now, before = _num(pulse.get(metric)), _num(baseline.get(metric))
        change = _rel(now, before)
        if change is None:
            continue
        rising = change >= 0
        table = up_table if rising else down_table
        if not table:
            continue
        severity = _by(table, abs(change))
        if severity is None:
            continue
        down_kind = RISK if up_kind == OPPORTUNITY else OPPORTUNITY
        kind = up_kind if rising else down_kind
        fired.append(Alert(
            id=f"{signal_id}_{'up' if rising else 'down'}", kind=kind,
            family=_PULSE_FAMILY.get(signal_id, "demand"), severity=severity,
            magnitude=min(100.0, abs(change) * 4.0), metric=metric,
            value=_pct(now) if unit == "%" else now,
            baseline=_pct(before) if unit == "%" else before,
            delta=change, unit=unit, evidence_metrics=(metric,),
        ))
    return sorted(fired, key=lambda a: (-_SEVERITY_RANK[a.severity], -a.magnitude, a.id))


SIGNALS: tuple[Signal, ...] = (
    freight_heavy, variation_depth_expected,
    design_fixable_share, assembly_burden, transit_damage_load,
    return_above_peers, return_below_peers, return_rising,
    demand_falling, demand_accelerating, conversion_weakening, offamazon_leading,
    price_erosion, premium_headroom,
    consolidating, fragmenting, amazon_entering, supply_outpacing_demand,
    entrenchment_rising,
    newcomer_window_open, newcomer_window_closing,
    quality_gap, pain_concentrated,
    keyword_supply_gap,
    ad_dependence, organic_winnable,
)

# Signals that contradict each other by construction: one column read both ways.
# Only one can fire on real numbers, but a partially-filled month can trip both,
# and two opposite alerts side by side discredit the whole panel.
_EXCLUSIVE: tuple[frozenset[str], ...] = (
    frozenset({"return_above_peers", "return_below_peers"}),
    frozenset({"consolidating", "fragmenting"}),
    frozenset({"demand_falling", "demand_accelerating"}),
    frozenset({"newcomer_window_open", "newcomer_window_closing"}),
    frozenset({"ad_dependence", "organic_winnable"}),
)


# -------------------------------------------------------------- localisation ----
# The bilingual templates live here rather than in the frontend dictionary
# because the model brief is built from the same strings: one wording, one place
# to fix it.

_TEXT: dict[str, dict[str, tuple[str, str]]] = {
    "freight_heavy": {
        "zh": ("平均单件 {value} lb，运费把成本下限定死了",
               "货架平均重量 {value} lb、平均体积 {volume} in³。重量在草图阶段就决定了运费档、破损率和退货成本，量产后改不动。"),
        "en": ("Average unit {value} lb — freight sets the cost floor",
               "Shelf average {value} lb and {volume} in³. Weight fixes the freight tier, the damage rate and the cost of a return, and it is decided at the sketch stage."),
    },
    "variation_depth_expected": {
        "zh": ("变体深度高于部门中位",
               "头部 ASIN 变体数中位 {value}，部门中位 {baseline}（{asins} 个样本）。这个类目按系列卖，开模和备货要按系列算。"),
        "en": ("Variant depth above the department median",
               "Median {value} variations across the head ASINs against a department median of {baseline} ({asins} sampled). This category sells ranges; tooling and stock have to be planned that way."),
    },
    "design_fixable_share": {
        "zh": ("{value}% 的差评是设计能解决的",
               "可设计解决的主题合计占差评样本 {value}%（样本 {sample_size} 条）：{themes}。这部分归我们改，不归客服改。"),
        "en": ("{value}% of the complaints are design problems",
               "Design-fixable themes cover {value}% of the negative sample ({sample_size} reviews): {themes}. That share is ours to fix, not customer service's."),
    },
    "assembly_burden": {
        "zh": ("装配和缺件占差评 {value}%",
               "装配难、缺件、说明书三类合计 {value}%（样本 {sample_size} 条）：{themes}。五金件、公差和一张说明书是整份 BOM 里最便宜的改动。"),
        "en": ("Assembly and missing parts are {value}% of complaints",
               "Assembly difficulty, missing parts and instructions total {value}% ({sample_size} reviews): {themes}. Hardware, tolerance and an instruction sheet are the cheapest changes in the BOM."),
    },
    "transit_damage_load": {
        "zh": ("运输破损占差评 {value}%",
               "破损类差评 {value}%（样本 {sample_size} 条），货架平均重量 {weight} lb。这是包装课题，而且破损退货这门生意要付两次运费。"),
        "en": ("Transit damage is {value}% of complaints",
               "Damage themes cover {value}% of the negative sample ({sample_size} reviews) at a {weight} lb shelf average. That is a packaging brief, and a damaged return is freight paid twice."),
    },
    "return_above_peers": {
        "zh": ("退货率是同级的 {multiple} 倍",
               "本期 {value}%，同级类目均值 {baseline}%。大件家具一次退货通常吃掉整单毛利。"),
        "en": ("Returns {multiple}× the peer average",
               "{value}% this period against a {baseline}% peer average. One freight return costs more than the order's margin."),
    },
    "return_below_peers": {
        "zh": ("退货率只有同级的 {multiple} 倍",
               "本期 {value}%，同级类目均值 {baseline}%。这是货运家具最实在的结构性成本优势。"),
        "en": ("Returns only {multiple}× the peer average",
               "{value}% against a {baseline}% peer average — a structural cost advantage for freight-shipped furniture."),
    },
    "return_rising": {
        "zh": ("退货率正在上升", "本期 {value}%，前三月均值 {baseline}%，上升 {delta} 个百分点。"),
        "en": ("Return rate is climbing",
               "{value}% this period against a {baseline}% trailing mean, up {delta} points."),
    },
    "demand_falling": {
        "zh": ("需求下滑", "销售额 {value}，前三月均值 {baseline}，下降 {delta}%。"),
        "en": ("Demand is falling",
               "Revenue {value} against a {baseline} trailing mean, down {delta}%."),
    },
    "demand_accelerating": {
        "zh": ("需求加速且快于大盘",
               "销售额 {value}，前三月均值 {baseline}，增长 {delta}%，高于部门中位。"),
        "en": ("Demand accelerating faster than the department",
               "Revenue {value} against {baseline}, up {delta}% — ahead of the department median."),
    },
    "price_erosion": {
        "zh": ("均价走低", "均价 {value}，前三月均值 {baseline}，下降 {delta}%。更像价格战而不是需求变化。"),
        "en": ("Average price eroding",
               "{value} against a {baseline} trailing mean, down {delta}% — a price war rather than a demand shift."),
    },
    "consolidating": {
        "zh": ("头部品牌集中度上升",
               "Top5 品牌销额占比 {value}%，前三月均值 {baseline}%，上升 {delta} 个百分点。"),
        "en": ("Top brands consolidating",
               "Top-5 brand revenue share {value}% against {baseline}%, up {delta} points."),
    },
    "fragmenting": {
        "zh": ("头部集中度下降，格局松动",
               "Top5 品牌销额占比 {value}%，前三月均值 {baseline}%，下降 {delta} 个百分点。"),
        "en": ("Market fragmenting",
               "Top-5 brand revenue share {value}% against {baseline}%, down {delta} points."),
    },
    "amazon_entering": {
        "zh": ("亚马逊自营占比偏高", "自营销额占比 {value}%。自营进场会同时压价格和压流量。"),
        "en": ("Amazon's own share is high",
               "Amazon-self revenue share {value}%. Amazon entering compresses both price and traffic."),
    },
    "supply_outpacing_demand": {
        "zh": ("在售增速快于销额增速",
               "在售 {signed_value}%，销额 {signed_baseline}%，差 {delta} 个百分点 —— 同一笔钱被更多链接分。"),
        "en": ("Listings growing faster than revenue",
               "Listings {signed_value}% against revenue {signed_baseline}%, a {delta}-point spread — the same money split more ways."),
    },
    "entrenchment_rising": {
        "zh": ("头部评论墙在加厚", "头部链接平均评论数 {value}，前三月均值 {baseline}，上升 {delta}%。"),
        "en": ("The review moat is deepening",
               "Head listings average {value} ratings against {baseline}, up {delta}%."),
    },
    "newcomer_window_open": {
        "zh": ("新品窗口开着", "近 12 月上架的链接拿走了 {value}% 的销售额。"),
        "en": ("The newcomer window is open",
               "Listings under 12 months old hold {value}% of category revenue."),
    },
    "newcomer_window_closing": {
        "zh": ("新品窗口在收窄",
               "近 12 月新品占比 {value}%，前三月均值 {baseline}%，下降 {delta} 个百分点。"),
        "en": ("The newcomer window is narrowing",
               "New-listing share {value}% against {baseline}%, down {delta} points."),
    },
    "conversion_weakening": {
        "zh": ("搜索转化低于同级", "搜索购买比 {value}，同级均值 {baseline} —— 流量进得来，钱留不下。"),
        "en": ("Conversion below the neighbourhood",
               "Search-to-purchase {value} against a {baseline} peer average."),
    },
    "quality_gap": {
        "zh": ("有钱但评分低", "类目均分 {value}★，销售额 {extra_revenue}。买家在花钱，但并不满意。"),
        "en": ("Money here, ratings are not",
               "Category average {value}★ on {extra_revenue} of revenue — buyers are paying and not happy."),
    },
    "premium_headroom": {
        "zh": ("{band} 价格带愿意付钱",
               "该价格带占销售额 {value}%，却只占在售 {baseline}%，高出 {delta} 个百分点。"),
        "en": ("The {band} band pays up",
               "It holds {value}% of revenue on only {baseline}% of listings — a {delta}-point gap."),
    },
    "keyword_supply_gap": {
        "zh": ("{value} 个高供需比词缺供给",
               "最高供需比 {top_sdr}：{keywords}。需求落在供给没覆盖的尺寸或功能颗粒度上。"),
        "en": ("{value} keywords with unmet supply",
               "Top supply-demand ratio {top_sdr}: {keywords}."),
    },
    "offamazon_leading": {
        "zh": ("站外热度领先站内",
               "Google Trends 近三月 {value}，此前 {baseline}，上升 {delta}%，快于亚马逊端。"),
        "en": ("Off-Amazon interest is leading",
               "Google Trends {value} over the last three months against {baseline}, up {delta}% — faster than the Amazon side."),
    },
    "pain_concentrated": {
        "zh": ("「{theme}」占差评 {value}%，且可由设计解决", "样本 {sample_size} 条差评。"),
        "en": ("“{theme}” is {value}% of negative reviews and fixable in design",
               "Sample of {sample_size} negative reviews."),
    },
    "ad_dependence": {
        "zh": ("头部流量靠广告",
               "头部 ASIN 广告流量占比均值 {value}% —— 进场门槛是广告预算，不是评论数。"),
        "en": ("Head traffic is paid",
               "Ad traffic averages {value}% across the head ASINs — entry is priced in ad budget, not reviews."),
    },
    "pulse_runrate_up": {
        "zh": ("单链接销售额在走高", "当下 {value}／链接，上月 {baseline}，上升 {delta}%。"),
        "en": ("Revenue per listing is rising",
               "{value} per listing now against {baseline} last month, up {delta}%."),
    },
    "pulse_runrate_down": {
        "zh": ("单链接销售额在走低", "当下 {value}／链接，上月 {baseline}，下降 {delta}%。"),
        "en": ("Revenue per listing is falling",
               "{value} per listing now against {baseline} last month, down {delta}%."),
    },
    "pulse_price_up": {
        "zh": ("均价在抬升", "当下 {value}，上月 {baseline}，上升 {delta}%。"),
        "en": ("Price level is rising", "{value} now against {baseline} last month, up {delta}%."),
    },
    "pulse_price_down": {
        "zh": ("均价在下滑", "当下 {value}，上月 {baseline}，下降 {delta}% —— 本月可能正在打价格战。"),
        "en": ("Price level is sliding",
               "{value} now against {baseline}, down {delta}% — a price war may be under way this month."),
    },
    "pulse_reviewwall_up": {
        "zh": ("头部评论墙本月在加厚", "头部平均评论数 {value}，上月 {baseline}，上升 {delta}%。"),
        "en": ("The review moat is thickening this month",
               "Head listings average {value} against {baseline}, up {delta}%."),
    },
    "pulse_sellers_up": {
        "zh": ("卖家数本月在增加", "当下 {value} 家，上月 {baseline} 家，上升 {delta}%。"),
        "en": ("Sellers are arriving this month",
               "{value} now against {baseline} last month, up {delta}%."),
    },
    "pulse_newcomers_up": {
        "zh": ("新品涌入加快", "新品占比 {value}%，上月 {baseline}%，上升 {delta}%。"),
        "en": ("New listings are arriving faster",
               "New-listing share {value}% against {baseline}%, up {delta}%."),
    },
    "pulse_newcomers_down": {
        "zh": ("新品涌入放缓", "新品占比 {value}%，上月 {baseline}%，下降 {delta}%。"),
        "en": ("New listings are slowing",
               "New-listing share {value}% against {baseline}%, down {delta}%."),
    },
    "pulse_rating_down": {
        "zh": ("类目满意度本月在掉", "均分 {value}★，上月 {baseline}★，下降 {delta}% —— 现有产品没解决的问题正在放大。"),
        "en": ("Satisfaction is slipping this month",
               "Average {value}★ against {baseline}★, down {delta}% — the unsolved problems are getting louder."),
    },
    "organic_winnable": {
        "zh": ("自然流量仍是主力", "头部 ASIN 自然流量占比均值 {value}% —— 内容和关键词还打得动。"),
        "en": ("Organic traffic still carries the head",
               "Natural traffic averages {value}% across the head ASINs."),
    },
}


def _fmt(value: float | None, unit: str) -> str:
    if value is None:
        return "—"
    if unit == "$":
        if abs(value) >= 1_000_000:
            return f"${value / 1_000_000:,.2f}M"
        if abs(value) >= 1_000:
            return f"${value / 1_000:,.1f}K"
        return f"${value:,.0f}"
    if abs(value) >= 1000:
        return f"{value:,.0f}"
    return f"{value:,.2f}".rstrip("0").rstrip(".")


def _signed(value: float | None, unit: str) -> str:
    if value is None:
        return "—"
    return f"+{_fmt(value, unit)}" if value >= 0 else _fmt(value, unit)


def describe(alert: Alert, language: str = "zh") -> tuple[str, str]:
    """One alert's title and detail. An unknown id degrades to the raw id."""
    entry = _TEXT.get(alert.id)
    if not entry:
        return alert.id, ""
    title, detail = entry.get(language) or entry["zh"]
    fields: dict[str, Any] = {
        "value": _fmt(alert.value, alert.unit),
        "baseline": _fmt(alert.baseline, alert.unit),
        # Growth-spread templates need the sign to come from the number, not from
        # a literal "+" in the text — otherwise a decline prints as "+-21.7%".
        "signed_value": _signed(alert.value, alert.unit),
        "signed_baseline": _signed(alert.baseline, alert.unit),
        "delta": _fmt(abs(alert.delta) if alert.delta is not None else None, ""),
        "extra_revenue": _fmt(_num(alert.extra.get("revenue")), "$"),
    }
    for key, value in alert.extra.items():
        fields[key] = (", ".join(str(v) for v in value)
                       if isinstance(value, list) else value)
    try:
        return title.format(**fields), detail.format(**fields)
    except (KeyError, IndexError):  # a template naming a field this alert lacks
        return title.split("{")[0].strip() or alert.id, ""


# ----------------------------------------------------------------- scanning ----

def scan(facts: NodeFacts) -> list[Alert]:
    """Every signal that fires for one node, most severe first."""
    fired: list[Alert] = []
    for signal in SIGNALS:
        try:
            alert = signal(facts)
        except (TypeError, ValueError, ZeroDivisionError):
            # A malformed warehouse row must not take the whole panel down.
            continue
        if alert is not None:
            fired.append(alert)

    by_id = {alert.id: alert for alert in fired}
    for pair in _EXCLUSIVE:
        present = [by_id[i] for i in pair if i in by_id]
        if len(present) > 1:
            keep = max(present, key=lambda a: (_SEVERITY_RANK[a.severity], a.magnitude))
            for alert in present:
                if alert is not keep:
                    by_id.pop(alert.id, None)
    return sorted(by_id.values(),
                  key=lambda a: (-_SEVERITY_RANK[a.severity], -a.magnitude, a.id))


def peer_medians(
    snapshots: Sequence[Mapping[str, Any]],
    histories: Mapping[str, Sequence[Mapping[str, Any]]],
) -> dict[str, float | None]:
    """Department-wide medians, so each node is judged against its siblings.

    Computed once per render and handed to every node: a threshold that moves
    with the department cannot be made obsolete by one good or bad quarter.
    """
    growths: list[float] = []
    for path, history in histories.items():
        facts = NodeFacts(node_key=path, history=history,
                          snapshot=history[-1] if history else {})
        change = _rel(_snap(facts, "total_revenue"), _baseline(facts, "total_revenue"))
        if change is not None:
            growths.append(change)

    def median_of(key: str) -> float | None:
        values = [v for v in (_num(s.get(key)) for s in snapshots) if v is not None]
        return _median(values)

    return {
        "revenue_growth_pct": _median(growths),
        # Filled by the caller from the product rows — variation depth lives on
        # listings, not on the category snapshot, and "a lot of variants" only
        # means anything against what the rest of the department ships.
        "variations": None,
        "total_revenue": median_of("total_revenue"),
        "avg_price": median_of("avg_price"),
        "avg_rating": median_of("avg_rating"),
        "return_ratio": median_of("return_ratio"),
        "avg_weight": median_of("avg_weight"),
        "avg_volume": median_of("avg_volume"),
        "top5_brand_crn": median_of("top5_brand_crn"),
        "new_ratio_l12": median_of("new_ratio_l12"),
    }


def serialize(alert: Alert, *, node_key: str, label: str, language: str,
              evidence_ids: Sequence[str] = ()) -> dict:
    title, detail = describe(alert, language)
    return {
        "id": alert.id,
        "key": f"{node_key}|{alert.id}",
        "kind": alert.kind,
        "family": alert.family,
        "severity": alert.severity,
        "magnitude": round(alert.magnitude, 1),
        "node_key": node_key,
        "label": label,
        "title": title,
        "detail": detail,
        "metric": alert.metric,
        "value": alert.value,
        "baseline": alert.baseline,
        "delta": alert.delta,
        "unit": alert.unit,
        "evidence_ids": list(evidence_ids),
    }


def split(alerts: Sequence[dict], *, limit: int | None = None) -> dict:
    """Risks and opportunities as two ranked lists, plus a severity tally."""
    risks = [a for a in alerts if a["kind"] == RISK]
    opportunities = [a for a in alerts if a["kind"] == OPPORTUNITY]
    if limit is not None:
        risks, opportunities = risks[:limit], opportunities[:limit]
    return {
        "risks": risks,
        "opportunities": opportunities,
        "counts": {
            "risk_high": len([a for a in risks if a["severity"] == HIGH]),
            "risk_total": len(risks),
            "opportunity_high": len([a for a in opportunities if a["severity"] == HIGH]),
            "opportunity_total": len(opportunities),
        },
    }


def rank(alerts: Sequence[dict]) -> list[dict]:
    return sorted(alerts, key=lambda a: (-_SEVERITY_RANK.get(a["severity"], 0),
                                         -a.get("magnitude", 0.0), a["key"]))


def diversify(alerts: Sequence[dict], *, per_signal: int = MAX_PER_SIGNAL) -> list[dict]:
    """Rank, then stop any one signal from filling the whole board.

    A department-wide move — Amazon expanding into furniture, a season turning —
    fires the same signal on every node at once. Ranked purely by severity that
    is a board saying one thing twelve times, which crowds out the eleven other
    things that are also true. The repeats are not dropped, only demoted behind
    the distinct findings, so the full picture is still reachable by scrolling
    and the headline is still the worst thing happening.
    """
    out: list[dict] = []
    for severity in (HIGH, MEDIUM, LOW):
        tier = [a for a in rank(alerts) if a["severity"] == severity]
        kept: list[dict] = []
        overflow: list[dict] = []
        seen: dict[str, int] = {}
        for alert in tier:
            count = seen.get(alert["id"], 0) + 1
            seen[alert["id"]] = count
            (kept if count <= per_signal else overflow).append(alert)
        out += kept + overflow
    # Anything with an unrecognised severity still has to come back, at the end.
    out += [a for a in rank(alerts) if a["severity"] not in _SEVERITY_RANK]
    return out


def brief(bundle: Mapping[str, Any], language: str) -> str:
    """The alert list as prose for the model — its only monitoring input.

    The model summarises this; it does not produce it. Handing it the finished
    list is what makes "the risk section cannot invent a risk" true rather than
    merely requested.
    """
    lines: list[str] = [
        "风险信号（服务端确定性计算，不得新增未列出的风险）：" if language == "zh"
        else "RISK SIGNALS (computed server-side; do not add risks that are not listed):"
    ]
    for alert in bundle.get("risks", []):
        lines.append(f"- [{alert['severity']}] {alert['label']}: "
                     f"{alert['title']}. {alert['detail']}")
    if not bundle.get("risks"):
        lines.append("- （无）" if language == "zh" else "- (none)")
    lines.append("机会信号：" if language == "zh" else "OPPORTUNITY SIGNALS:")
    for alert in bundle.get("opportunities", []):
        lines.append(f"- [{alert['severity']}] {alert['label']}: "
                     f"{alert['title']}. {alert['detail']}")
    if not bundle.get("opportunities"):
        lines.append("- （无）" if language == "zh" else "- (none)")
    return "\n".join(lines)
