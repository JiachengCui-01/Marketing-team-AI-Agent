"""Opportunity scoring. Deterministic, server-side, computed from database columns.

The model never produces a score — the publish tools have no field for one, and
:func:`score_category` / :func:`score_product` overwrite anything that shows up
anyway. Three reasons, each learned from the v1 implementation:

* The board is a **ranking**. A model re-reading the same payload transcribes
  slightly differently every run, and rank churn from an LLM re-read is
  indistinguishable from a real market move.
* ``aov_fit`` is read off the department's own revenue-by-price-band histogram
  rather than from a curve somebody wrote down. Which price a category sells at
  is a fact about the market, and the market publishes it every month; asserting
  it as a constant meant the board could not notice the shelf moving.
* v1 recomputed the score from the model's own formatted strings
  (``_number("$638,074")``), so one transcription slip silently became a score.
  Reading ``REAL`` columns deletes that whole class of bug.

**A missing input scores zero, never an average.** Imputing would rank a category
with no data above one with bad data. Coverage is reported separately as
``confidence`` so "72 out of a partly-observed model" is visible rather than hidden.
"""
from __future__ import annotations

import re
from typing import Any, Mapping, Sequence

FORMULA_VERSION = 3

CATEGORY_WEIGHTS: dict[str, float] = {
    "demand_scale": 10,
    "demand_growth": 20,
    "aov_fit": 15,
    "concentration": 15,
    "entrenchment": 12,
    "new_product_viability": 20,
    "keyword_sdr": 8,
}
PRODUCT_WEIGHTS: dict[str, float] = {
    "demand": 20,
    "growth": 12,
    "aov_fit": 14,
    "competition": 14,
    "quality_fit": 8,
    "pain_headroom": 16,
    "keyword_headroom": 16,
}
RISK_KEY = "return_risk"
RISK_MAX = 15.0

# Breakpoint tables map a raw value to 0-100; the weight then scales it. Tables are
# read as "at x, score y", linearly interpolated between, flat outside.
_DEMAND_SCALE = ((0.0, 0.0), (200_000.0, 25.0), (1_000_000.0, 60.0),
                 (3_000_000.0, 85.0), (10_000_000.0, 100.0))
_DEMAND_GROWTH = ((-40.0, 0.0), (-10.0, 20.0), (0.0, 40.0), (10.0, 65.0),
                  (25.0, 85.0), (50.0, 100.0))
# Top-5 brand revenue share, as a percentage. The curve inverts it: low share is
# an opening, high share is a wall.
_CONCENTRATION = ((10.0, 100.0), (25.0, 85.0), (40.0, 60.0), (55.0, 35.0),
                  (70.0, 15.0), (90.0, 0.0))
_ENTRENCHMENT = ((0.0, 100.0), (150.0, 95.0), (500.0, 75.0), (1_500.0, 50.0),
                 (4_000.0, 25.0), (10_000.0, 8.0), (30_000.0, 0.0))
# Share of revenue held by listings under 12 months old, as a percentage.
_NEW_VIABILITY = ((0.0, 0.0), (3.0, 20.0), (8.0, 55.0), (15.0, 80.0), (25.0, 100.0))
# Supply/demand ratio as the vendor reports it: searches per listing. Higher is
# more demand chasing less supply.
_KEYWORD_SDR = ((0.0, 0.0), (5.0, 20.0), (15.0, 55.0), (35.0, 85.0), (80.0, 100.0))
# Return rate relative to the sibling-category average. The vendor ships the
# benchmark alongside the rate, which is the only way 1.6% is readable as good.
_RETURN_RISK = ((0.4, 0.0), (0.8, 3.0), (1.0, 6.0), (1.5, 11.0), (2.5, 15.0))

# v1 curves kept verbatim so scores stay roughly comparable across the upgrade.
_REVIEW_DEPTH = ((0.0, 100.0), (100.0, 100.0), (500.0, 80.0), (2_000.0, 55.0),
                 (5_000.0, 30.0), (10_000.0, 15.0), (50_000.0, 0.0))
# Deliberately non-monotonic: 4.2 scores highest and 4.9 lower, because a 4.9 with
# forty thousand reviews is an entrenched incumbent, not an opening. A model asked
# to "judge rating quality" reliably gets this backwards.
_QUALITY_FIT = ((0.0, 0.0), (3.5, 20.0), (3.8, 65.0), (4.2, 100.0), (4.5, 85.0),
                (5.0, 60.0))
_BSR_TREND = ((-60.0, 100.0), (-20.0, 80.0), (0.0, 50.0), (20.0, 25.0), (60.0, 0.0))
_PAIN_HEADROOM = ((0.0, 0.0), (2.0, 15.0), (5.0, 45.0), (10.0, 75.0), (18.0, 100.0))


# ------------------------------------------------------------- price model ----
# ``aov_fit`` used to be a constant: a curve peaking around $300-900, written to
# encode this company's freight economics. It was defended in this module's
# docstring as "a constant, not an inference", and that defence was half right —
# the freight floor is a fact about the business, but *where the money sits* is a
# fact about the market, and the constant was asserting both.
#
# Now the shape comes from the department's own revenue-by-price-band histogram:
# the bands the peer categories actually take their money in. A category priced
# where the department's revenue concentrates scores high; one priced out at a
# tail scores low, whether that tail is cheap or expensive.

# What the shipped curve says, kept for exactly one purpose: scoring before any
# price distribution has been collected. A board that scored every category zero
# on price for its first month would rank on noise.
_AOV_FALLBACK = ((0.0, 0.0), (120.0, 10.0), (200.0, 45.0), (300.0, 80.0),
                 (450.0, 100.0), (900.0, 100.0), (1_400.0, 70.0), (2_500.0, 35.0),
                 (4_000.0, 10.0))

_BAND_RANGE = re.compile(r"(\d+(?:\.\d+)?)\s*[-–~]\s*(\d+(?:\.\d+)?)")
_BAND_OPEN = re.compile(r"(?:>|≥|over|above)?\s*(\d+(?:\.\d+)?)\s*\+?$")


def band_bounds(label: str) -> tuple[float, float] | None:
    """``"150-200"`` → ``(150, 200)``; ``"1000+"`` → ``(1000, 2000)``.

    An open-ended top band is given a finite width so it has a midpoint like
    every other band. Doubling is arbitrary but bounded, and the alternative —
    dropping the band — throws away the one that usually holds the premium
    revenue this business cares most about.
    """
    text = str(label or "").replace("$", "").replace(",", "").strip().lower()
    if not text:
        return None
    match = _BAND_RANGE.search(text)
    if match:
        low, high = float(match.group(1)), float(match.group(2))
        return (low, high) if high > low else None
    match = _BAND_OPEN.search(text)
    if match:
        low = float(match.group(1))
        return low, low * 2.0
    return None


# Listings, not vendor bins, are the preferred input. The vendor returns three
# or four price bands per node and its top band is a property of its binning, not
# of the market — treating "no band above $200" as "nobody buys above $200" would
# be the same kind of assertion this change exists to remove. Real listings carry
# their own prices and cover the range the department actually sells in.
MIN_PRICE_ROWS = 20
PRICE_BINS = 8


def price_model_from_listings(
    products: Sequence[Mapping[str, Any]],
) -> tuple[tuple[float, float], ...] | None:
    """A price → 0-100 curve from the department's own listings.

    Equal-count bins: every bin holds the same number of listings, so the
    differences between them are purely about where the revenue is, not about how
    wide somebody drew the bucket. The bin's median price is its x, its summed
    revenue is its y, and the whole curve is normalised so the fattest bin is 100.

    ``None`` when there are too few priced listings to bin — the caller falls
    back rather than scoring a whole board off nine products.
    """
    pairs = sorted(
        (price, revenue)
        for price, revenue in ((_num(p.get("price")), _num(p.get("revenue")))
                               for p in products)
        if price and price > 0 and revenue and revenue > 0)
    if len(pairs) < MIN_PRICE_ROWS:
        return None
    size = max(2, len(pairs) // PRICE_BINS)
    points: list[tuple[float, float]] = []
    for start in range(0, len(pairs), size):
        chunk = pairs[start:start + size]
        if len(chunk) < 2:
            # Fold a stray tail into the bin before it rather than let two
            # listings define their own price band.
            break
        prices = [price for price, _revenue in chunk]
        points.append((_median(prices) or prices[0],
                       sum(revenue for _price, revenue in chunk)))
    if len(points) < 2:
        return None
    peak = max(value for _mid, value in points)
    if peak <= 0:
        return None
    return tuple((mid, value / peak * 100.0) for mid, value in points)


def price_model(bands: Sequence[Mapping[str, Any]]) -> tuple[tuple[float, float], ...]:
    """The same curve from the vendor's price bands, for when listings are thin.

    Points are (band midpoint, revenue normalised so the fattest band is 100).
    ``piecewise`` interpolates between them and holds flat outside — which is the
    honest behaviour here precisely because the band list is truncated: the
    absence of a band above the top one is the absence of a *bucket*, not
    evidence that nobody buys there.

    Returns the shipped fallback when the bands carry no revenue — not an empty
    curve, because a factor that scores zero for every category would silently
    delete its own weight from the ranking.
    """
    points: list[tuple[float, float]] = []
    for band in bands:
        bounds = band_bounds(band.get("bucket_key") or band.get("label"))
        revenue = _num(band.get("revenue"))
        if bounds is None or revenue is None or revenue <= 0:
            continue
        points.append(((bounds[0] + bounds[1]) / 2.0, revenue))
    if len(points) < 2:
        return _AOV_FALLBACK
    peak = max(value for _mid, value in points)
    if peak <= 0:
        return _AOV_FALLBACK
    points.sort(key=lambda p: p[0])
    return tuple((mid, value / peak * 100.0) for mid, value in points)


def price_curve_rows(curve: Sequence[tuple[float, float]]) -> list[dict]:
    """The curve as rows a panel can show. Empty while the fallback is in use, so
    the UI shows nothing rather than presenting a shipped constant as a reading."""
    if tuple(curve) == _AOV_FALLBACK:
        return []
    return [{"price": round(mid), "fit": round(value, 1)} for mid, value in curve]


def clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def piecewise(value: float | None, points: Sequence[tuple[float, float]]) -> float:
    """Interpolate ``value`` through a breakpoint table. ``None`` scores zero.

    Zero, not an average: an imputed score makes a category with no data outrank a
    category with bad data.
    """
    if value is None:
        return 0.0
    if value <= points[0][0]:
        return points[0][1]
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        if value <= x1:
            return y0 + (value - x0) * (y1 - y0) / (x1 - x0)
    return points[-1][1]


def _num(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _median(values: Sequence[float]) -> float | None:
    clean = sorted(v for v in values if v is not None)
    if not clean:
        return None
    mid = len(clean) // 2
    return clean[mid] if len(clean) % 2 else (clean[mid - 1] + clean[mid]) / 2


def growth_pct(series: Sequence[dict], key: str = "total_revenue") -> float | None:
    """First-to-last percentage change across a monthly series."""
    values = [_num(point.get(key)) for point in series]
    values = [v for v in values if v is not None and v > 0]
    if len(values) < 2:
        return None
    return (values[-1] - values[0]) / values[0] * 100.0


def growth_span(series: Sequence[dict], key: str = "total_revenue") -> tuple[str, str]:
    """The first and last period :func:`growth_pct` actually compared.

    Shipped alongside the number because the window is not fixed: it is however
    many months of this node we happen to hold, which is two for a node we
    started tracking last month and twenty-four for one we did not. A figure
    labelled "year on year" that is really "since last month" is worse than no
    label, and that is what the treemap legend used to say.
    """
    usable = [point for point in series
              if (_num(point.get(key)) or 0) > 0 and point.get("period")]
    if len(usable) < 2:
        return "", ""
    return str(usable[0]["period"]), str(usable[-1]["period"])


def new_revenue_share_pct(snapshot: dict) -> float | None:
    """Share of category revenue held by listings under 12 months old.

    Preferred over the raw listing count share: ten new listings that sell nothing
    prove the category is *open*, which is not the same as *enterable*.
    """
    count = _num(snapshot.get("new_count_l12"))
    new_avg = _num(snapshot.get("new_avg_revenue_l12"))
    total = _num(snapshot.get("total_revenue"))
    if count and new_avg and total:
        return min(100.0, count * new_avg / total * 100.0)
    ratio = _num(snapshot.get("new_ratio_l12"))
    return ratio * 100.0 if ratio is not None else None


def return_risk_input(snapshot: dict) -> float | None:
    """Return rate as a multiple of the sibling-category average.

    1.6% means nothing on its own; 1.6% against a 2.9% neighbourhood average means
    this category returns *less* than its peers, which for freight-shipped
    furniture is one of the strongest signals available.
    """
    rate = _num(snapshot.get("return_ratio"))
    benchmark = _num(snapshot.get("return_ratio_avg"))
    if rate is None:
        return None
    if benchmark and benchmark > 0:
        return rate / benchmark
    # No benchmark: fall back to the absolute rate against a 3% reference, which is
    # roughly the furniture department's own average.
    return rate / 0.03


def _assemble(
    weights: dict[str, float], points: dict[str, float | None], risk_points: float | None,
) -> dict:
    """Turn per-factor 0-100 readings into a weighted score plus its breakdown."""
    breakdown: dict[str, float] = {}
    missing: list[str] = []
    covered = 0.0
    for factor, weight in weights.items():
        reading = points.get(factor)
        if reading is None:
            missing.append(factor)
            breakdown[factor] = 0.0
            continue
        covered += weight
        breakdown[factor] = round(weight * clamp(reading) / 100.0, 1)
    penalty = 0.0 if risk_points is None else round(min(RISK_MAX, max(0.0, risk_points)), 1)
    if risk_points is None:
        missing.append(RISK_KEY)
    breakdown[RISK_KEY] = -penalty
    total = sum(v for k, v in breakdown.items() if k != RISK_KEY) - penalty
    return {
        "score": round(clamp(total)),
        "breakdown": breakdown,
        "missing": missing,
        "confidence": round(covered / sum(weights.values()), 2) if weights else 0.0,
        "formula_version": FORMULA_VERSION,
    }


def score_category(
    snapshot: dict, *, history: Sequence[dict] = (), keywords: Sequence[dict] = (),
    aov_curve: Sequence[tuple[float, float]] | None = None,
) -> dict:
    """Score one category-month from its stored facts.

    ``aov_curve`` comes from :func:`price_model` over the department's price
    bands. Defaulted rather than required so a caller with no distribution — a
    test, a cold warehouse — still scores something explainable.
    """
    snapshot = snapshot or {}
    curve = tuple(aov_curve) if aov_curve else _AOV_FALLBACK
    concentration = _num(snapshot.get("top5_brand_crn"))
    entrenchment = _num(snapshot.get("hl_avg_ratings")) or _num(snapshot.get("avg_ratings"))
    sdr = _median([_num(k.get("supply_demand_ratio")) for k in keywords]) if keywords else None

    points = {
        "demand_scale": piecewise(_num(snapshot.get("total_revenue")), _DEMAND_SCALE),
        "demand_growth": piecewise(growth_pct(history), _DEMAND_GROWTH)
                         if growth_pct(history) is not None else None,
        "aov_fit": piecewise(_num(snapshot.get("avg_price")), curve)
                   if _num(snapshot.get("avg_price")) is not None else None,
        # Stored as a fraction; the curve is written in percentage points.
        "concentration": piecewise(concentration * 100.0, _CONCENTRATION)
                         if concentration is not None else None,
        "entrenchment": piecewise(entrenchment, _ENTRENCHMENT)
                        if entrenchment is not None else None,
        "new_product_viability": piecewise(new_revenue_share_pct(snapshot), _NEW_VIABILITY)
                                 if new_revenue_share_pct(snapshot) is not None else None,
        "keyword_sdr": piecewise(sdr, _KEYWORD_SDR) if sdr is not None else None,
    }
    if _num(snapshot.get("total_revenue")) is None:
        points["demand_scale"] = None
    risk = return_risk_input(snapshot)
    risk_points = piecewise(risk, _RETURN_RISK) if risk is not None else None
    return _assemble(CATEGORY_WEIGHTS, points, risk_points)


def score_product(
    metrics: dict, *, snapshot: dict | None = None, history: Sequence[dict] = (),
    keywords: Sequence[dict] = (), pain: Sequence[dict] = (),
    aov_curve: Sequence[tuple[float, float]] | None = None,
) -> dict:
    """Score one product opportunity anchored on a real ASIN."""
    metrics = metrics or {}
    snapshot = snapshot or {}
    curve = tuple(aov_curve) if aov_curve else _AOV_FALLBACK

    units = _num(metrics.get("units"))
    revenue = _num(metrics.get("revenue"))
    demand = None
    if units is not None or revenue is not None:
        demand = (50.0 * clamp((units or 0.0) / 5_000.0 * 100.0) / 100.0
                  + 50.0 * clamp((revenue or 0.0) / 500_000.0 * 100.0) / 100.0)

    category_growth = growth_pct(history)
    bsr_change = _num(metrics.get("bsr_cr"))
    growth = None
    if category_growth is not None or bsr_change is not None:
        growth = (0.58 * (piecewise(category_growth, _DEMAND_GROWTH)
                          if category_growth is not None else 0.0)
                  + 0.42 * (piecewise(bsr_change, _BSR_TREND)
                            if bsr_change is not None else 0.0))

    concentration = _num(snapshot.get("top5_brand_crn"))
    reviews = _num(metrics.get("ratings"))
    competition = None
    if concentration is not None or reviews is not None:
        competition = (0.5 * (piecewise(concentration * 100.0, _CONCENTRATION)
                              if concentration is not None else 0.0)
                       + 0.5 * (piecewise(reviews, _REVIEW_DEPTH)
                                if reviews is not None else 0.0))

    sdr = _median([_num(k.get("supply_demand_ratio")) for k in keywords]) if keywords else None
    points = {
        "demand": demand,
        "growth": growth,
        "aov_fit": piecewise(_num(metrics.get("price")), curve)
                   if _num(metrics.get("price")) is not None else None,
        "competition": competition,
        "quality_fit": piecewise(_num(metrics.get("rating")), _QUALITY_FIT)
                       if _num(metrics.get("rating")) is not None else None,
        "pain_headroom": piecewise(pain_headroom_input(pain), _PAIN_HEADROOM)
                         if pain else None,
        "keyword_headroom": piecewise(sdr, _KEYWORD_SDR) if sdr is not None else None,
    }
    risk = return_risk_input(snapshot)
    risk_points = piecewise(risk, _RETURN_RISK) if risk is not None else None
    return _assemble(PRODUCT_WEIGHTS, points, risk_points)


def pain_headroom_input(themes: Sequence[dict]) -> float | None:
    """Negative share × fixable share, in percentage points.

    The model names and classifies the themes; the arithmetic is here. That split
    is what keeps the factor stable while still letting a model read the language.
    """
    if not themes:
        return None
    total = sum(_num(t.get("mention_count")) or 0.0 for t in themes)
    if total <= 0:
        return None
    fixable = sum((_num(t.get("mention_count")) or 0.0) for t in themes
                  if t.get("fixable_in_design"))
    sample = max((_num(t.get("sample_size")) or 0.0) for t in themes)
    if sample <= 0:
        return None
    negative_share = min(1.0, total / sample)
    return negative_share * (fixable / total) * 100.0


def score_model() -> dict:
    """Shipped with every response so the UI renders breakdown bars from the weights
    instead of hardcoding ``/30`` and silently desyncing when a weight changes."""
    return {
        "version": f"v{FORMULA_VERSION}",
        "category_weights": dict(CATEGORY_WEIGHTS),
        "product_weights": dict(PRODUCT_WEIGHTS),
        "risk_key": RISK_KEY,
        "risk_max": RISK_MAX,
    }
