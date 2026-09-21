"""The deterministic half of both dashboards: every number, before any model runs.

Split out of ``render`` because the two halves fail differently and are tested
differently. Everything here is a pure read of SQLite — no vendor, no model, no
network — so a test builds a warehouse, calls a builder and asserts on numbers.
``render`` keeps the model orchestration, the citation validation and the three
outcomes.

The guiding constraint is that the vendor's data types should all reach a screen.
A family that is collected, billed for and then never rendered is worse than one
that is never collected: it costs the same and teaches nobody anything. So the
builders below read every table the collectors write, and ``coverage`` reports
what landed so a silently missing family is visible rather than merely absent.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, MutableMapping, Sequence

from . import elements, gateway, jobs, monitor, scoring, store, taxonomy

MAX_BOARD_ROWS = 24
MAX_COMPETITORS = 12
MAX_KEYWORDS = 25
MAX_OPPORTUNITIES = 4
# Both direction lists are read top to bottom; past a dozen nobody does.
MAX_DIRECTION_ROWS = 12
MAX_HISTORY_ASINS = 4
MAX_EDGE_ASINS = 3

# Families the collectors write, in the order the coverage panel lists them. The
# label pair is bilingual here for the same reason the monitor's is: the model
# brief and the screen must not drift apart.
COVERAGE_FAMILIES: tuple[tuple[str, str, str, str], ...] = (
    ("category_structure", "market_research", "类目结构", "Category structure"),
    ("category_statistics", "market_research_statistics", "头部listing统计", "Head-listing stats"),
    ("demand_trend", "market_product_demand_trend", "需求与退货", "Demand and returns"),
    ("newcomer_metrics", "market_research", "新品可行性", "Newcomer viability"),
    ("fulfilment_mix", "market_research", "配送结构", "Fulfilment mix"),
    ("distribution_price", "market_price_distribution", "价格带分布", "Price bands"),
    ("distribution_listing_date", "market_listing_date_distribution", "上架时间分布", "Listing age"),
    ("distribution_rating", "market_rating_distribution", "评分分布", "Rating spread"),
    ("distribution_ratings_count", "market_ratings_count_distribution", "评论数分布", "Review-count spread"),
    ("distribution_ebc", "market_ebc_distribution", "A+ 内容分布", "A+ content"),
    ("distribution_seller_country", "market_seller_country_distribution", "卖家国别分布", "Seller countries"),
    ("concentration_brand", "market_brand_concentration", "品牌集中度", "Brand concentration"),
    ("concentration_seller_type", "market_seller_type_concentration", "卖家类型集中度", "Seller-type mix"),
    ("concentration_seller", "market_seller_concentration", "卖家集中度", "Seller concentration"),
    ("concentration_product", "market_product_concentration", "商品集中度", "Product concentration"),
    ("product_research", "product_research", "ASIN 指标", "ASIN metrics"),
    ("asin_prediction", "asin_prediction", "ASIN 历史", "ASIN history"),
    ("keyword_research", "keyword_research / aba_research_monthly", "关键词需求", "Keyword demand"),
    ("traffic_keyword", "traffic_keyword", "关键词流量边", "Keyword-to-ASIN traffic"),
    ("traffic_source", "traffic_source", "流量构成", "Traffic mix"),
    ("google_trend", "google_trend", "站外热度", "Off-Amazon demand"),
    ("review", "review", "评论痛点", "Review pain points"),
)


# ------------------------------------------------------------------ format ----

def pct(value: Any) -> float | None:
    number = scoring._num(value)
    return None if number is None else round(number * 100.0, 2)


def money(value: Any) -> str:
    number = scoring._num(value)
    if number is None:
        return "—"
    if abs(number) >= 1_000_000:
        return f"${number / 1_000_000:,.2f}M"
    if abs(number) >= 1_000:
        return f"${number / 1_000:,.1f}K"
    return f"${number:,.0f}"


def tile(label: str, value: str, hint: str = "", estimated: bool = False,
         observed: bool = False, computed: bool = False) -> dict:
    """One KPI, and where its number came from.

    Three sources, all marked, because an unmarked tile used to mean any of them
    and a reader cannot tell those apart:

    * ``observed`` — read off the listing or the category page. A price, a rating,
      a listing count.
    * ``estimated`` — the vendor's model. Every money figure is one: Amazon
      publishes category units and revenue to nobody, so SellerSprite infers them
      from BSR, and a finished month does not change that.
    * ``computed`` — our own arithmetic. A score, a signal count. Not a market
      fact at all, which is worth saying before it gets read as one.
    """
    return {"label": label, "value": value, "hint": hint,
            "estimated": estimated,
            "observed": observed and not estimated,
            "computed": computed and not (estimated or observed)}


def filled(tiles: Sequence[dict]) -> list[dict]:
    """Drop the tiles that have no number behind them.

    A KPI reading "—" is not a KPI; it is the absence of one, and a row of them
    makes the ones that did arrive harder to find. What is missing is still said
    once — by the coverage strip and the gap list — rather than once per tile.
    """
    out = []
    for item in tiles:
        value = str(item.get("value") or "")
        # A composite value like "— / — / —" is just as empty as a bare dash, and
        # it slips past an equality check.
        if not value.replace("—", "").replace("/", "").replace("%", "").strip():
            continue
        out.append(item)
    return out


def _zh(language: str) -> bool:
    return language != "en"


# --------------------------------------------------------------- monitoring ----

def node_facts(
    marketplace: str, node_id_path: str, period: str, *,
    snapshot: Mapping[str, Any] | None = None,
    peers: Mapping[str, float | None] | None = None,
    label: str = "",
    deep: bool = True,
) -> monitor.NodeFacts:
    """Assemble one node's monitoring inputs from the warehouse.

    ``deep=False`` skips the per-ASIN and review reads. The board scans twelve
    nodes and those two tables only hold rows for the flagships, so the cheap
    pass is not a reduced signal set — it is the same set minus the signals that
    would find nothing anyway.
    """
    snap = snapshot if snapshot is not None else (
        store.get_node_snapshot(marketplace, node_id_path, period) or {})
    return monitor.NodeFacts(
        node_key=node_id_path,
        label=label or taxonomy.short_label(taxonomy.label_for(node_id_path, marketplace)),
        snapshot=snap,
        history=store.snapshot_history(marketplace, node_id_path),
        keywords=store.top_keywords(marketplace, node_id_path, period, limit=MAX_KEYWORDS),
        products=(store.top_products(marketplace, node_id_path, period, limit=MAX_COMPETITORS)
                  if deep else ()),
        themes=(store.review_themes(marketplace, node_id_path, period) if deep else ()),
        distributions=store.all_distributions(marketplace, node_id_path, period),
        concentration=store.all_concentration(marketplace, node_id_path, period),
        trend_index=store.keyword_series(marketplace, node_id_path),
        peers=peers or {},
    )


def alerts_for(facts: monitor.NodeFacts, marketplace: str, period: str,
               language: str) -> list[dict]:
    """Scan one node and resolve each alert's metric names to evidence ids."""
    out: list[dict] = []
    for alert in monitor.scan(facts):
        ids: list[str] = []
        if alert.evidence_metrics:
            found = store.evidence_ids_by_metric(
                marketplace, "node", facts.node_key, period, alert.evidence_metrics)
            ids = [found[m] for m in alert.evidence_metrics if m in found]
        out.append(monitor.serialize(alert, node_key=facts.node_key, label=facts.label,
                                     language=language, evidence_ids=ids))
    return out


def coverage(marketplace: str, period: str, language: str) -> dict:
    """Which vendor data families reached the warehouse this period."""
    counts = store.coverage_counts(marketplace, period)
    rows = []
    for key, tool, label_zh, label_en in COVERAGE_FAMILIES:
        rows.append({
            "key": key,
            "tool": tool,
            "label": label_zh if _zh(language) else label_en,
            "rows": int(counts.get(key, 0)),
            "present": bool(counts.get(key, 0)),
        })
    present = len([r for r in rows if r["present"]])
    return {"families": rows, "present": present, "total": len(rows)}


# ------------------------------------------------------------- current month ----
# The board proper describes the last month the vendor closed. This describes the
# month in flight, and it is a different kind of statement: a live reading of the
# shelf, compared like-for-like against that closed month.
#
# What it deliberately cannot show is revenue, units sold, returns or
# concentration. Those are monthly aggregates and for an open month they do not
# exist — not "are small", do not exist. Everything below comes from the one
# category tool that answers for an open month, and nothing is extrapolated into
# a total without saying so.

PULSE_METRICS: tuple[tuple[str, str, str, str], ...] = (
    ("avg_revenue", "$", "单链接月销售额", "Revenue per listing"),
    ("avg_units", "", "单链接月销量", "Units per listing"),
    ("avg_price", "$", "均价", "Average price"),
    ("sellers", "", "卖家数", "Sellers"),
    ("brands", "", "品牌数", "Brands"),
    ("avg_rating", "★", "类目均分", "Average rating"),
    ("hl_avg_ratings", "", "头部评论数", "Head-listing reviews"),
    ("new_product_proportion", "%", "新品占比", "New-listing share"),
)


def _delta_pct(now: Any, before: Any) -> float | None:
    a, b = scoring._num(now), scoring._num(before)
    if a is None or b in (None, 0):
        return None
    return round((a - b) / abs(b) * 100.0, 1)


def _pulse_row(pulse: Mapping[str, Any], baseline: Mapping[str, Any],
               zh: bool) -> list[dict]:
    out = []
    for key, unit, label_zh, label_en in PULSE_METRICS:
        now = scoring._num(pulse.get(key))
        if now is None:
            continue
        before = scoring._num(baseline.get(key))
        out.append({
            "key": key,
            "label": label_zh if zh else label_en,
            "unit": unit,
            "now": pct(now) if unit == "%" else now,
            "baseline": (pct(before) if unit == "%" else before) if before is not None else None,
            "delta_pct": _delta_pct(now, before),
        })
    return out


def _implied_pace(pulse: Mapping[str, Any], baseline: Mapping[str, Any]) -> dict | None:
    """How this month is tracking against the last closed one, as a multiple.

    A ratio rather than a projected total, and that is the whole point. The
    vendor's ``totalRevenue`` covers the ~100 head listings it analyses, not the
    category's full shelf — ``totalRevenue / avgRevenue`` is exactly 100 while
    ``totalProducts`` is 1816 — so multiplying a live per-listing rate by a
    listing count produces a number roughly eighteen times too large. Dividing
    two per-listing rates cancels the sample entirely and needs no assumption
    about how many listings the vendor looked at, as long as it looked at the
    same number both months.

    Still an inference: it says the head of the category is selling at N× last
    month's pace, not that the month will end at N× last month's revenue.
    """
    now = scoring._num(pulse.get("avg_revenue"))
    before = scoring._num(baseline.get("avg_revenue"))
    if now is None or not before:
        return None
    return {
        "ratio": round(now / before, 2),
        "now": now,
        "baseline": before,
        "delta_pct": _delta_pct(now, before),
        "estimated": True,
    }


def build_current(marketplace: str, language: str, *,
                  node_id_path: str | None = None) -> dict:
    """The month in flight: live readings, their deltas, and the early warnings.

    Returns ``{"available": False}`` rather than an empty shell when no pulse has
    been taken — a panel of em-dashes reads as breakage, and "not collected yet"
    is a different statement from "nothing is happening".
    """
    zh = _zh(language)
    pulses = store.latest_pulse(marketplace)
    if node_id_path:
        pulses = [p for p in pulses if p["node_id_path"] == node_id_path]
    if not pulses:
        return {"available": False, "period": gateway.current_period(),
                "baseline_period": store.latest_period(marketplace)}

    baseline_period = store.latest_period(marketplace)
    rows: list[dict] = []
    alerts: list[dict] = []
    for pulse in pulses:
        path = pulse["node_id_path"]
        baseline = (store.get_node_snapshot(marketplace, path, baseline_period)
                    if baseline_period else None) or {}
        label = taxonomy.short_label(pulse.get("node_label_path") or path)
        metrics = _pulse_row(pulse, baseline, zh)
        if not metrics:
            continue
        rows.append({
            "node_key": path,
            "label": label,
            "observed_at": pulse.get("observed_at"),
            "metrics": metrics,
            "implied_pace": _implied_pace(pulse, baseline),
        })
        for alert in monitor.scan_pulse(pulse, baseline):
            ids: list[str] = []
            if alert.evidence_metrics and baseline_period:
                found = store.evidence_ids_by_metric(
                    marketplace, "node", path, gateway.current_period(),
                    alert.evidence_metrics)
                ids = [found[m] for m in alert.evidence_metrics if m in found]
            alerts.append(monitor.serialize(alert, node_key=path, label=label,
                                            language=language, evidence_ids=ids))

    observed = [r["observed_at"] for r in rows if r.get("observed_at")]
    return {
        "available": bool(rows),
        "period": gateway.current_period(),
        "baseline_period": baseline_period,
        "observed_at": max(observed) if observed else None,
        "rows": rows,
        "monitor": monitor.split(monitor.diversify(alerts),
                                 limit=monitor.MAX_OVERVIEW_ALERTS),
    }


# ----------------------------------------------------------------- overview ----

# Floors for the chart's axis range. Without them a chart whose specs all sit
# within a point of each other would be zoomed until the gaps between them
# looked meaningful, and a chart of low-share specs would push the median line
# off the frame. x is in percentage points of head revenue; y is in stars, where
# a quarter of a star is already a wide gap between two ratings.
#
# Floors, not frames: the axis is otherwise fitted to the points on it. x used
# to run to a fixed five points of head revenue, which on a real board — where
# the busiest spec holds two — spent well over half the width on empty shelf
# and pushed every dot into the left quarter of the chart.
MIN_X_SPAN = 0.8
MIN_Y_SPAN = 0.25
# A reading this far clear of the rest of the pack stops setting the axis:
# half the span it would otherwise claim, all to itself. One spec rated a star
# and a half under the board is a real reading, and letting it own five sixths
# of the height squeezes the other forty-four into a band at the top. Past the
# fence a point is pinned to the frame edge and drawn pinned — still on the
# chart, still in the hover card, no longer paying for the whole axis.
#
# The share is always measured against the span the readings started with, and
# never against what is left after a trim. Against the shrinking span it
# cascades: shelf shares are Pareto-shaped, so every step down the tail is a
# large fraction of the little that remains, and a run of trims eats the four
# biggest specs on the board — which are the four the chart exists to show.
OUTLIER_GAP_SHARE = 0.5
# And never more than this share of them, so a genuinely wide spread is drawn
# wide instead of trimmed down to its middle.
MAX_TRIMMED_SHARE = 0.1
# How many specs one chart may plot. A spec is a narrow claim, so the tail is
# long and mostly one-listing noise; the count of what was measured is reported
# beside the chart so the tail is visible without being drawn.
MAX_COMBO_POINTS = 45


def _combo_matrix(combos: Sequence[dict], zh: bool) -> dict:
    """The spec chart: one point per combination the market has actually built.

    x is what the spec holds of head revenue; y is how well the market does it —
    the spec's revenue-weighted rating against the median of every spec on the
    board. The corner that matters is bottom-right: real money, and the listings
    taking it are not liked. That is a product brief.

    y used to be search growth, and the chart came out blank. Demand is the
    strict reading — one phrase has to carry every term of the spec — and almost
    no phrase does, so sixty specs sat in the rail saying "not measured", which
    is honest and useless. A rating is observed on every listing the spec was
    read off, so the axis is answerable for the whole chart, and "who is doing
    this badly" is at least as much a product question as "what is growing".

    One chart rather than a row per attribute, because a spec spans the
    attributes by construction — there is no attribute to file it under.
    """
    rated = [c for c in combos if c.get("rating") is not None]
    y_mid = scoring._median([c["rating"] for c in rated]) or 0.0
    points = [
        {"key": c["key"], "label": c["label"], "kind": "combo",
         "kind_label": (f"{c['attrs']} 项组合" if zh
                        else f"{c['attrs']}-attribute spec"),
         "spec": c["spec"],
         "shelf_pct": c["revenue_share_pct"] if c.get("shelf_rated") else None,
         # Signed against the board median, because a bare 4.3 means nothing
         # until you know what the shelf around it scores.
         "rating_gap": (round(c["rating"] - y_mid, 2)
                        if c.get("rating") is not None else None),
         "rating": c.get("rating"),
         "reviews": c.get("reviews"),
         "revenue": c.get("revenue") or 0.0,
         "asins": c["asins"],
         "avg_price": c["avg_price"]}
        for c in combos
        if c.get("shelf_rated") or c.get("rating") is not None
    ]
    if not points:
        return {"points": [], "bounds": None, "scale": None,
                "quadrants": _quadrant_names(zh)}
    points.sort(key=lambda p: p["revenue"], reverse=True)
    x_mid = scoring._median(
        [p["shelf_pct"] for p in points if p["shelf_pct"] is not None]) or 0.0
    return {
        "points": points[:MAX_COMBO_POINTS],
        "bounds": _chart_bounds(points[:MAX_COMBO_POINTS], x_mid, y_mid),
        "scale": _dot_scale(points[:MAX_COMBO_POINTS]),
        "total": len(combos),
        "quadrants": _quadrant_names(zh),
    }


def drop_stale_combos(dashboard: MutableMapping[str, Any]) -> None:
    """Blank a stored spec chart whose points predate the rating axis.

    The board is rendered on demand and a saved one can sit for days, so a
    deploy that changes a chart's axes meets its own old payloads. Those points
    carry search growth and no rating, and the chart would draw every one of
    them in the "rating not measured" rail — a claim about the market rather
    than about the record. Blanked instead: the section hides itself until the
    next render, which is free.
    """
    combos = dashboard.get("element_combos")
    if not isinstance(combos, dict):
        return
    points = combos.get("points") or []
    if points and all("rating_gap" not in p for p in points):
        combos["points"] = []
        combos["bounds"] = None
        combos["scale"] = None


def _quadrant_names(zh: bool) -> tuple[str, str, str, str]:
    """Clockwise from top-left, named for the decision the corner implies."""
    return (("盘子小 · 口碑已做好", "钱多 · 口碑已做好（红海）",
             "钱多 · 口碑差（切入点）", "盘子小 · 口碑差")
            if zh else
            ("Thin shelf, well rated", "Shelf-heavy, well rated (crowded)",
             "Shelf-heavy, poorly rated (the opening)", "Thin and poorly rated"))


def _fitted(values: Sequence[float]) -> tuple[float, float]:
    """The interval the readings actually occupy, minus any detached extreme.

    Sorted, then walked in from whichever end has the wider gap to its
    neighbour. A value separated from the next one in by half of the readings'
    whole span is not describing the distribution any more, it is dragging the
    frame; a tail that steps down evenly has no such gap and is kept whole. The
    walk stops at a tenth of the points, so a spread that is genuinely wide is
    drawn wide.
    """
    ordered = sorted(values)
    lo, hi = 0, len(ordered) - 1
    span = ordered[hi] - ordered[lo]
    if span <= 0:
        return ordered[lo], ordered[hi]
    budget = int(len(ordered) * MAX_TRIMMED_SHARE)
    while budget > 0 and hi - lo >= 2:
        low_gap = ordered[lo + 1] - ordered[lo]
        high_gap = ordered[hi] - ordered[hi - 1]
        # The span here is the one the readings arrived with, deliberately: see
        # OUTLIER_GAP_SHARE.
        if max(low_gap, high_gap) < span * OUTLIER_GAP_SHARE:
            break
        if low_gap >= high_gap:
            lo += 1
        else:
            hi -= 1
        budget -= 1
    return ordered[lo], ordered[hi]


def _padded(lo: float, hi: float, min_span: float) -> tuple[float, float]:
    """A little air around the readings, and never a frame thinner than the
    floor — a span of zero is what a board of one spec would otherwise ask for.
    """
    room = max(hi - lo, min_span) * 0.06
    lo, hi = lo - room, hi + room
    if hi - lo < min_span:
        middle = (lo + hi) / 2
        lo, hi = middle - min_span / 2, middle + min_span / 2
    return lo, hi


def _chart_bounds(points: Sequence[dict], x_mid: float, y_mid: float) -> dict:
    """Axis bounds, fitted to the points actually being drawn.

    The frame follows the distribution rather than standing still in front of
    it: whatever the board looks like this month, the dots should fill the
    chart. The floors are what stop a chart of near-identical specs from being
    zoomed until noise looks like signal, and both reference lines are forced
    inside the frame — a chart that draws a median it cannot show is worse than
    one with some slack in it.
    """
    shelves = [p["shelf_pct"] for p in points if p["shelf_pct"] is not None]
    gaps = [p["rating_gap"] for p in points if p["rating_gap"] is not None]
    x_lo, x_hi = _fitted(shelves) if shelves else (0.0, MIN_X_SPAN)
    y_lo, y_hi = _fitted(gaps) if gaps else (-MIN_Y_SPAN, MIN_Y_SPAN)
    # The two dashed lines are drawn off these bounds, so both have to be
    # reachable: the vertical one at the median share, the horizontal one at the
    # board median rating, which is a gap of zero.
    x_lo, x_hi = _padded(min(x_lo, x_mid), max(x_hi, x_mid), MIN_X_SPAN)
    y_lo, y_hi = _padded(min(y_lo, 0.0), max(y_hi, 0.0), MIN_Y_SPAN)
    # Zero is a real reading on a share axis — it means "holds none of the head"
    # — so the frame keeps it whenever the smallest spec is anywhere near it,
    # rather than cutting the axis to win a few pixels. A share is never
    # negative either way.
    x_lo = 0.0 if x_lo <= (x_hi - x_lo) * 0.25 else max(0.0, x_lo)
    return {
        "x_min": round(x_lo, 2),
        "x_max": round(x_hi, 2),
        "x_mid": x_mid,
        "y_min": round(y_lo, 2),
        "y_max": round(y_hi, 2),
        # The rating the zero line stands for, so it can be named rather than
        # left as an unexplained 0.
        "y_mid": round(y_mid, 2),
    }


def _dot_scale(points: Sequence[dict]) -> dict | None:
    """What the largest dot area means: the biggest head revenue on show."""
    if not points:
        return None
    return {"max_revenue": max(1.0, max(p["revenue"] for p in points))}


# How many points the opportunity quadrant plots. Higher than the spec chart's
# cap because a point here carries a category as well as a look: thirteen
# shelves with half a dozen live openings each is the reading, and a cap of
# forty-five is what leaves a reader asking where their category went.
MAX_SPEC_POINTS = 96
# Floor for the quadrant's y axis, in percentage points of a node's head
# revenue. A look that moved a tenth of a point did not move, and without a
# floor a board of flat months would be zoomed until it looked like weather.
MIN_SHIFT_SPAN = 1.5


def _every_shelf_first(points: Sequence[dict], cap: int) -> list[dict]:
    """Fill the chart a round at a time, one spec per shelf, biggest shelf first.

    A straight top-N by revenue spends the whole chart on sofas and beds and
    leaves the small categories off it entirely — which is the complaint the
    category map earned, in a chart with six times as many points to spend. So
    every shelf gets its best spec before any shelf gets its second.
    """
    by_node: dict[str, list[dict]] = {}
    for point in points:
        by_node.setdefault(point["node_key"], []).append(point)
    kept: list[dict] = []
    for rank in range(max((len(group) for group in by_node.values()), default=0)):
        for group in by_node.values():
            if rank < len(group):
                kept.append(group[rank])
                if len(kept) >= cap:
                    return sorted(kept, key=lambda p: p["revenue"], reverse=True)
    return sorted(kept, key=lambda p: p["revenue"], reverse=True)


def _spec_map(specs: Sequence[dict], board: Sequence[dict], zh: bool,
              *, window: tuple[str, str]) -> dict:
    """The opportunity quadrant, over specs rather than over categories.

    A category map says "work in Nightstands". Nobody can draw that. The unit
    here is the sentence a brief is written from — room, shelf, colour, look —
    because those are the four decisions that produce a drawing, and because a
    category's average hides the thing worth finding: the one corner of a
    crowded shelf that three brands have not taken yet.

    x is 可进入度, what is left of the cell after its three largest brands.
    y is the cell's share of its own shelf against last month, in percentage
    points. Both are read off the listings; neither is modelled. A cell whose
    node has no comparison month keeps its x and loses its y — it goes to the
    chart's rail rather than being drawn at zero or dropped, which is what the
    category map did to every category whose growth we could not measure.
    """
    rows = {row["node_key"]: row for row in board}
    # What the card calls the two category rows. Named apart from
    # ``taxonomy.area_label`` below, which answers a different question.
    area_row, node_row = ("大致品类", "细分品类") if zh else ("Area", "Category")
    points: list[dict] = []
    for spec in specs:
        row = rows.get(spec["node_key"])
        if not row:
            continue
        area = taxonomy.area_label(row.get("node_label_path") or "")
        points.append({
            "key": spec["key"],
            "node_key": spec["node_key"],
            "area": area,
            "node_label": row["label"],
            # Printed on the chart where it fits: the shelf first, because that
            # is what a reader scans for, then the two decisions.
            "label": " · ".join([row["label"]]
                                + [part["label"] for part in spec["spec"]]),
            # The card's rows. The category is part of the spec here, not a
            # caption on it — a look is only open or crowded somewhere.
            "spec": ([{"kind": "area", "kind_label": area_row, "label": area},
                      {"kind": "node", "kind_label": node_row,
                       "label": row["label"]}]
                     + list(spec["spec"])),
            "color": spec["color"],
            "look": spec["look"],
            "entry": spec["entry"],
            "share_shift_pp": spec["share_shift_pp"],
            "share_pct": spec["share_pct"],
            "share_before_pct": spec["share_before_pct"],
            "revenue": spec["revenue"],
            "asins": spec["asins"],
            "brands": spec["brands"],
            "avg_price": spec["avg_price"],
            "rating": spec["rating"],
            "reviews": spec["reviews"],
            # The shelf's own return rate, carried rather than drawn: it belongs
            # to the category and not to the look, so it is a row in the card
            # and never a position on the chart.
            "return_risk": row.get("return_risk") or 0.0,
        })
    points.sort(key=lambda p: p["revenue"], reverse=True)
    shown = _every_shelf_first(points, MAX_SPEC_POINTS)
    if not shown:
        return {"points": [], "bounds": None, "scale": None, "areas": [],
                "total": 0, "window": {"from": window[0], "to": window[1]}}
    shifts = [p["share_shift_pp"] for p in shown if p["share_shift_pp"] is not None]
    entries = [p["entry"] for p in shown]
    areas: dict[str, dict] = {}
    for point in shown:
        bucket = areas.setdefault(point["area"],
                                  {"area": point["area"], "count": 0, "revenue": 0.0})
        bucket["count"] += 1
        bucket["revenue"] = round(bucket["revenue"] + point["revenue"], 2)
    return {
        "points": shown,
        "bounds": {
            # 0 and 100 mean something on this axis — owned outright, and owned
            # by nobody — so the frame starts at zero rather than at the
            # smallest reading. The top end follows the points, because at this
            # grain nothing reaches 100 and a fixed frame would spend half its
            # width on empty shelf.
            "x_min": 0.0,
            "x_max": round(min(100.0, max(65.0, max(entries) * 1.08)), 1),
            # The median of what is drawn, not a fixed 50: three brands inside
            # one colour of one shelf are not comparable to five brands across
            # a whole category, so the line has to say "more open than the
            # typical spec on this board" rather than pretend to an absolute.
            "x_mid": round(scoring._median(entries) or 0.0, 1),
            "y_min": round(min([-MIN_SHIFT_SPAN] + shifts) * 1.15, 2),
            "y_max": round(max([MIN_SHIFT_SPAN] + shifts) * 1.15, 2),
        },
        "scale": _dot_scale(shown),
        "areas": sorted(areas.values(), key=lambda a: a["revenue"], reverse=True),
        "total": len(points),
        # Which two months the y axis compared, so nothing downstream has to
        # guess whether "last month" means the calendar's or ours.
        "window": {"from": window[0], "to": window[1]},
    }


def _follow(board: Sequence[dict], rising: Sequence[dict], zh: bool) -> list[dict]:
    """What to put on the product roadmap, and the one reason why.

    Two kinds of entry, because a product programme needs both halves: a category
    says where to build, an element says what the thing should look like. Each
    carries the number that put it on the list, so the recommendation can be
    argued with rather than only obeyed.
    """
    out: list[dict] = []
    for row in board:
        growth = scoring._num(row.get("growth_pct"))
        new_share = scoring._num(row.get("new_revenue_share_pct"))
        ret, peer = (scoring._num(row.get("return_ratio_pct")),
                     scoring._num(row.get("return_ratio_avg_pct")))
        reasons: list[str] = []
        if growth is not None and growth >= 10.0:
            reasons.append((f"销售额 {growth:+.1f}%" if zh else f"revenue {growth:+.1f}%"))
        # A newcomer share this high is the market saying a new listing can still
        # win — the single most important precondition for building anything.
        if new_share is not None and new_share >= 15.0:
            reasons.append((f"近 12 月新品占销额 {new_share:.1f}%" if zh
                            else f"new listings hold {new_share:.1f}% of revenue"))
        if ret is not None and peer and ret / peer <= 0.85:
            reasons.append((f"退货率只有同级 {ret / peer:.2f} 倍" if zh
                            else f"returns {ret / peer:.2f}x peers"))
        if not reasons:
            continue
        out.append({
            "kind": "category", "key": row["node_key"], "label": row["label"],
            "score": row["category_score"], "confidence": row["score_confidence"],
            "why": "，".join(reasons) if zh else "; ".join(reasons),
        })
    out.sort(key=lambda item: item.get("score") or 0, reverse=True)

    for element in rising:
        out.append({
            "kind": "element", "key": element["key"], "label": element["label"],
            "kind_label": element["kind_label"],
            "why": ((f"{element['keyword_count']} 个词合计 {element['searches']:,} 搜索，"
                     f"{element['growth_pct']:+.1f}%") if zh else
                    (f"{element['growth_pct']:+.1f}% across {element['keyword_count']} "
                     f"phrases, {element['searches']:,} searches")),
            "keywords": [k["keyword"] for k in element["keywords"][:3]],
        })
    return out[:MAX_DIRECTION_ROWS]


def _avoid(board: Sequence[dict], falling: Sequence[dict], zh: bool) -> list[dict]:
    """What not to start, and what to design out of whatever does get started."""
    out: list[dict] = []
    for row in board:
        growth = scoring._num(row.get("growth_pct"))
        ret, peer = (scoring._num(row.get("return_ratio_pct")),
                     scoring._num(row.get("return_ratio_avg_pct")))
        top5 = scoring._num(row.get("top5_brand_share_pct"))
        entrench = scoring._num(row.get("score_breakdown", {}).get("entrenchment"))
        reasons: list[str] = []
        if growth is not None and growth <= -10.0:
            reasons.append((f"销售额 {growth:+.1f}%" if zh else f"revenue {growth:+.1f}%"))
        if ret is not None and peer and ret / peer >= 1.25:
            reasons.append((f"退货率是同级 {ret / peer:.2f} 倍，货运退货吃掉整单毛利" if zh
                            else f"returns {ret / peer:.2f}x peers"))
        if top5 is not None and top5 >= 55.0:
            reasons.append((f"Top5 品牌占 {top5:.0f}% 销额" if zh
                            else f"top-5 brands hold {top5:.0f}% of revenue"))
        # entrenchment scores *high* when the review wall is low, so a near-zero
        # score is the wall itself: a new listing cannot climb it inside a year.
        if entrench is not None and entrench <= 2.0:
            reasons.append(("头部评论墙过高，新品一年内爬不上去" if zh
                            else "the head's review wall is not climbable in a year"))
        if not reasons:
            continue
        out.append({
            "kind": "category", "key": row["node_key"], "label": row["label"],
            "score": row["category_score"], "confidence": row["score_confidence"],
            "why": "，".join(reasons) if zh else "; ".join(reasons),
        })
    out.sort(key=lambda item: item.get("score") or 0)

    for element in falling:
        out.append({
            "kind": "element", "key": element["key"], "label": element["label"],
            "kind_label": element["kind_label"],
            "why": ((f"{element['keyword_count']} 个词合计 {element['searches']:,} 搜索，"
                     f"{element['growth_pct']:+.1f}%") if zh else
                    (f"{element['growth_pct']:+.1f}% across {element['keyword_count']} "
                     f"phrases, {element['searches']:,} searches")),
            "keywords": [k["keyword"] for k in element["keywords"][:3]],
        })
    return out[:MAX_DIRECTION_ROWS]


# Factor names live here as well as in the frontend dictionary for the reason
# monitor's templates do: the board's written read is built server-side, so the
# strings have to exist where the sentence is assembled.
_FACTOR_NAMES: dict[str, tuple[str, str]] = {
    "demand_scale": ("需求规模", "demand scale"),
    "demand_growth": ("需求增长", "demand growth"),
    "aov_fit": ("价格带适配", "price fit"),
    "concentration": ("竞争可入性", "competitive openness"),
    "entrenchment": ("评论壁垒", "review wall"),
    "new_product_viability": ("新品可行性", "new-entrant viability"),
    "keyword_sdr": ("关键词空间", "keyword headroom"),
}

# The eight jobs in jobs.NODE_PACK, named for a reader. A raw job kind in a
# sentence about a market reads as a leaked internal.
_MISSING_NAMES: dict[str, tuple[str, str]] = {
    "category_structure": ("类目结构", "category structure"),
    "category_demand": ("需求趋势", "demand trend"),
    "category_price_bands": ("价格带分布", "price bands"),
    "category_newcomers": ("新品表现", "new-entrant performance"),
    "category_brands": ("品牌格局", "brand landscape"),
    "product_pack": ("竞品包", "competitor pack"),
    "product_newcomers": ("新品竞品", "new-entrant listings"),
    "keyword_demand": ("关键词需求", "keyword demand"),
}


def _named_missing(missing: Sequence[str], zh: bool) -> list[str]:
    out = []
    for step in missing:
        names = _MISSING_NAMES.get(step)
        out.append((names[0] if zh else names[1]) if names else step)
    return out


def _board_read(row: Mapping[str, Any], node_alerts: Sequence[Mapping[str, Any]],
                zh: bool) -> list[dict]:
    """A written read for one board row, composed from stored columns and alerts.

    Every row gets one, including the rows that are mostly gaps — a card with a
    score and nothing else reads as a rendering failure, and the honest reading of
    a thin row ("we covered a quarter of the model, here is which quarter") is
    more useful than silence.

    Deterministic on purpose. The model's verdict rationale sits alongside this,
    not instead of it: a sentence that survives a model outage is the one people
    come to rely on.
    """
    lines: list[dict] = []
    breakdown = row.get("score_breakdown") or {}
    earned = [(key, value) for key, value in breakdown.items()
              if key != scoring.RISK_KEY and (scoring._num(value) or 0) > 0]
    earned.sort(key=lambda pair: pair[1], reverse=True)
    shortfall = sorted(
        ((key, weight - (scoring._num(breakdown.get(key)) or 0.0))
         for key, weight in scoring.CATEGORY_WEIGHTS.items()),
        key=lambda pair: pair[1], reverse=True)

    def name(key: str) -> str:
        names = _FACTOR_NAMES.get(key, (key, key))
        return names[0] if zh else names[1]

    # 1. Why it sits where it sits.
    if earned:
        best = "、".join(name(k) for k, _v in earned[:2]) if zh else \
            " and ".join(name(k) for k, _v in earned[:2])
        # "earned nothing" would be a lie about a factor that earned 6 of 15;
        # the honest form is the points forgone, which is also the actionable one.
        weak_key, lost = shortfall[0] if shortfall else ("", 0.0)
        weak = name(weak_key) if lost >= 5 else ""
        got = scoring._num(breakdown.get(weak_key)) or 0.0
        cap = scoring.CATEGORY_WEIGHTS.get(weak_key, 0)
        if zh:
            text = f"{row['category_score']} 分主要来自{best}"
            text += (f"；最大失分项是{weak}（{got:.0f}/{cap:.0f}）。" if weak else "。")
        else:
            text = f"Scores {row['category_score']} mainly on {best}"
            text += (f"; the biggest shortfall is {weak} ({got:.0f}/{cap:.0f})."
                     if weak else ".")
        lines.append({"kind": "read", "text": text})

    # 2. The physical and commercial constraints a product brief is written against.
    # Deliberately not the price, the revenue, the growth or the top-5 share: the
    # row's own metric strip already names those four, and a card that prints the
    # same number twice teaches people to skim past both.
    facts: list[str] = []
    weight = scoring._num(row.get("avg_weight"))
    if weight is not None:
        facts.append((f"平均 {round(weight, 1)} lb" if zh
                      else f"{round(weight, 1)} lb average"))
    ret, peer = (scoring._num(row.get("return_ratio_pct")),
                 scoring._num(row.get("return_ratio_avg_pct")))
    if ret is not None and peer:
        multiple = ret / peer
        if zh:
            facts.append(f"退货率 {ret:.2f}%，是同级 {multiple:.2f} 倍"
                         + ("（结构性成本优势）" if multiple <= 0.85 else
                            "（一次货运退货吃掉整单毛利）" if multiple >= 1.25 else ""))
        else:
            facts.append(f"returns {ret:.2f}%, {multiple:.2f}x peers")
    new_share = scoring._num(row.get("new_revenue_share_pct"))
    if new_share is not None:
        facts.append((f"近 12 月新品拿走 {new_share:.1f}% 销额" if zh
                      else f"new listings hold {new_share:.1f}% of revenue"))
    if facts:
        lines.append({"kind": "facts", "text": "；".join(facts) + "。" if zh
                      else "; ".join(facts) + "."})

    # 3. The strongest signal each way, named rather than summarised.
    for kind in ("opportunity", "risk"):
        hit = next((a for a in node_alerts if a.get("kind") == kind), None)
        if hit:
            lines.append({"kind": kind, "text": hit.get("title") or "",
                          "detail": hit.get("detail") or "",
                          "evidence_ids": hit.get("evidence_ids") or []})

    # 4. What was not collected — stated, because it bounds every line above.
    missing = _named_missing(row.get("missing") or [], zh)
    if missing and (row.get("score_confidence") or 1.0) < 0.6:
        lines.append({"kind": "gap", "text": (
            f"本期未采集：{'、'.join(missing)}。缺失项按 0 分计，"
            f"所以这个分数不能和覆盖完整的类目直接比。" if zh else
            f"Not collected: {', '.join(missing)}. Missing inputs score zero, so this "
            f"score is not comparable with a fully covered category.")})
    return lines


def _with_product_peers(peers: dict, marketplace: str, period: str) -> dict:
    """Add the department medians that live on listings rather than on snapshots."""
    products = store.all_products(marketplace, period)
    depth = scoring._median([v for v in (scoring._num(p.get("variations"))
                                         for p in products) if v is not None])
    return {**peers, "variations": depth}


def price_curve(marketplace: str, period: str) -> tuple[tuple[float, float], ...]:
    """Where the department's revenue sits by price, as a scoring curve.

    Computed once per render and handed to every node's score. Reading it per
    node would score each category against its own prices, which is circular —
    a category is always perfectly priced for itself.

    Listings first, vendor bands second, shipped constant last. Each step down is
    a step further from the market's own reading, and the panel shows which one
    was used so a score is never taken on faith.
    """
    from_listings = scoring.price_model_from_listings(
        store.all_products(marketplace, period))
    if from_listings is not None:
        return from_listings
    bands: dict[str, dict] = {}
    for node in taxonomy.leaf_nodes(marketplace):
        for bucket in store.get_distribution(marketplace, node["node_id_path"],
                                             period, "price"):
            entry = bands.setdefault(bucket["bucket_key"],
                                     {"bucket_key": bucket["bucket_key"], "revenue": 0.0})
            entry["revenue"] += bucket.get("revenue") or 0.0
    return scoring.price_model(list(bands.values()))


@dataclass(frozen=True)
class MiningInputs:
    """Everything the element read is computed from, fetched once per render.

    Three consumers want the same rows — the mining, the naming call and the
    spec chart — and each of them reading for itself meant the twenty-thousand
    row title scan ran two and three times for one dashboard.
    """
    products: list[dict]
    phrases: list[dict]
    before: list[dict]
    # The same listing rows for the comparison month, and which month that was.
    # The opportunity quadrant's y axis is a share against last month, so it
    # needs the titles twice; nothing else here does, and an empty list is the
    # honest answer when there is no earlier month stored.
    products_before: list[dict] = field(default_factory=list)
    before_period: str = ""


def mining_inputs(marketplace: str, period: str) -> MiningInputs:
    """The stored rows the element read takes in.

    None of the limits here is a quality bar — they are fetch caps over rows
    already bought and stored. At 400 phrases the demand side saw only the head
    of the department's search vocabulary, so an attribute whose terms live in
    the middle of that list could not appear at all, however real it was.
    Reading more stored rows costs a wider SELECT and nothing else.
    """
    before = gateway.step_period(period, -1)
    # Phrases compare against the calendar's previous month; listings compare
    # against the most recent month that actually has listings. The difference
    # matters: a phrase row missing is one term unrated, a listing month missing
    # would make every spec on the shelf look newly invented.
    comparison = next(iter(store.product_periods(marketplace, before=period)), "")
    return MiningInputs(
        # Every title held for the month. The old 2,500 was a third of what a
        # full month's listing pull collects, and the third it kept was the
        # revenue head — where the vocabulary is narrowest and most generic.
        products=store.all_products(marketplace, period,
                                    limit=elements.MAX_TITLE_ROWS),
        phrases=_demand_rows(marketplace, period),
        before=_demand_rows(marketplace, before) if before else [],
        products_before=(store.all_products(marketplace, comparison,
                                            limit=elements.MAX_TITLE_ROWS)
                         if comparison else []),
        before_period=comparison)


def mined_terms(marketplace: str, period: str, *,
                inputs: MiningInputs | None = None) -> list[dict]:
    """The design terms this month's data contains, before anything names them.

    Shared by the panel and by the naming call so there is exactly one answer to
    "which terms did we find" — two definitions would let the model classify a
    list the chart never draws.
    """
    mining = inputs or mining_inputs(marketplace, period)
    return elements.mine(mining.products, mining.phrases, previous=mining.before)


def _demand_rows(marketplace: str, period: str) -> list[dict]:
    """Every stored phrase for the month, from both places we keep them.

    The per-ASIN traffic keywords have been collected every month into the edge
    table and have never been part of this vocabulary, purely because the mining
    read one table and the collector wrote another. They are already paid for.

    Keyword-metric rows win a collision: they are the same phrase, but they carry
    the growth columns the edge rows do not, and growth is the axis that decides
    whether an element can be plotted at all.
    """
    rows = store.top_keywords(marketplace, None, period,
                              limit=elements.MAX_PHRASE_ROWS)
    seen = {str(r.get("keyword") or "").strip().lower() for r in rows}
    rows.extend(row for row in store.keyword_edge_phrases(
        marketplace, period, limit=elements.MAX_PHRASE_ROWS)
        if str(row.get("keyword") or "").strip().lower() not in seen)
    return rows


def build_overview(marketplace: str, period: str, language: str,
                   *, terms: Sequence[dict] | None = None,
                   inputs: MiningInputs | None = None) -> dict:
    """Every deterministic section of the discovery board."""
    zh = _zh(language)
    snapshots = {s["node_id_path"]: s for s in store.list_node_snapshots(marketplace, period)}
    histories = {path: store.snapshot_history(marketplace, path)
                 for path in snapshots}
    leaf_snapshots = [snapshots[n["node_id_path"]] for n in taxonomy.leaf_nodes(marketplace)
                      if n["node_id_path"] in snapshots]
    peers = _with_product_peers(monitor.peer_medians(
        leaf_snapshots,
        {path: history for path, history in histories.items()
         if path != taxonomy.FURNITURE_ROOT}), marketplace, period)

    totals = store.product_totals(marketplace, period)
    # One curve for the whole board, read off the department's own price bands.
    aov_curve = price_curve(marketplace, period)
    # Element demand is department-wide: a style does not belong to one node, and
    # reading it per node would split "fluted" across six categories and bury it.
    # Mined from the market's own words, then named by the model and cached.
    # Both halves come from calls the sweep already makes: the titles arrive with
    # every product_research row, the phrases with every keyword call.
    # `terms` and `inputs` are passed in by the render, which mined them a moment
    # ago to feed the naming call. Mining is the most expensive read on this path
    # — every stored title and phrase for two months, then the whole term pass —
    # and doing it twice per render bought nothing but a second identical answer.
    mining = inputs or mining_inputs(marketplace, period)
    element_rows = elements.apply_naming(
        mined_terms(marketplace, period, inputs=mining) if terms is None else terms,
        store.element_naming(marketplace), zh)
    rising_elements, falling_elements = elements.split(element_rows)
    board: list[dict] = []
    alerts: list[dict] = []
    for node in taxonomy.leaf_nodes(marketplace):
        path = node["node_id_path"]
        snap = snapshots.get(path)
        if not snap:
            continue
        history = histories.get(path, [])
        keywords = store.top_keywords(marketplace, path, period, limit=20)
        score = scoring.score_category(snap, history=history, keywords=keywords,
                                       aov_curve=aov_curve)
        completeness, missing = jobs.node_completeness(marketplace, path, period)
        label = taxonomy.short_label(node["node_label_path"])
        board.append({
            "node_key": path,
            "node_label_path": node["node_label_path"],
            "label": label,
            "brand_category": node.get("brand_category"),
            "category_score": score["score"],
            "score_breakdown": score["breakdown"],
            "score_confidence": score["confidence"],
            # Which factors had no reading. A factor scored zero because the
            # market is bad at it and one scored zero because nobody measured it
            # are the same number and different sentences, and the card now
            # shows every factor, so it has to be able to tell them apart.
            "score_missing": score["missing"],
            "revenue_est": snap.get("total_revenue"),
            # The wider figure: every ASIN row we hold for this node, summed.
            "covered_revenue": (totals.get(path) or {}).get("revenue"),
            "covered_asins": (totals.get(path) or {}).get("asins") or 0,
            "product_pool": snap.get("product_pool"),
            "product_tail_pct": snap.get("product_tail_pct"),
            "growth_pct": scoring.growth_pct(history),
            # The window that figure covers, so nothing downstream has to guess
            # whether it means "since last month" or "year on year".
            "growth_from": scoring.growth_span(history)[0],
            "growth_to": scoring.growth_span(history)[1],
            "median_price": snap.get("avg_price"),
            "avg_weight": snap.get("avg_weight"),
            "avg_volume": snap.get("avg_volume"),
            "top5_brand_share_pct": pct(snap.get("top5_brand_crn")),
            "new_revenue_share_pct": scoring.new_revenue_share_pct(snap),
            "return_ratio_pct": pct(snap.get("return_ratio")),
            "return_ratio_avg_pct": pct(snap.get("return_ratio_avg")),
            "return_risk": -score["breakdown"].get(scoring.RISK_KEY, 0.0),
            "completeness": completeness,
            "missing": missing,
        })
        facts = node_facts(marketplace, path, period, snapshot=snap, peers=peers,
                           label=label, deep=True)
        alerts += alerts_for(facts, marketplace, period, language)

    board.sort(key=lambda row: row["category_score"], reverse=True)
    board = board[:MAX_BOARD_ROWS]
    shown = {row["node_key"] for row in board}
    alerts = [a for a in alerts if a["node_key"] in shown]

    # Ranked alerts per node, so each row's read names its strongest signal each
    # way rather than whichever one happened to be scanned first.
    ranked = monitor.rank(alerts)
    for row in board:
        row["read"] = _board_read(
            row, [a for a in ranked if a["node_key"] == row["node_key"]], zh)

    root = snapshots.get(taxonomy.FURNITURE_ROOT) or {}
    # Summing `or 0.0` over rows that are all None yields 0.0, and the board then
    # states "$0 monthly revenue" — a measurement — when the truth is that nothing
    # was collected. Sum only what exists, and report nothing when nothing does.
    observed = [row["revenue_est"] for row in board if row["revenue_est"] is not None]
    head_revenue = scoring._num(root.get("total_revenue"))
    if head_revenue is None:
        head_revenue = sum(observed) if observed else None
    coverage_stats = _coverage_totals(board)
    rising = sorted([r for r in board if (r["growth_pct"] or 0) > 0],
                    key=lambda r: r["growth_pct"], reverse=True)[:5]
    declining = sorted([r for r in board if (r["growth_pct"] or 0) < 0],
                       key=lambda r: r["growth_pct"])[:5]
    watch = monitor.split(monitor.diversify(alerts), limit=monitor.MAX_OVERVIEW_ALERTS)
    families = coverage(marketplace, period, language)

    # Eight, in two rows of four. The break lands between "how big is this shelf
    # and how much of it did we read" and "where do we go, what do we watch".
    # The vendor-data-family count is gone from here: the coverage strip below
    # names every family and says which ones landed, so a bare "12/22" at the top
    # was a worry with nowhere to go.
    kpis = [
        _revenue_tile(coverage_stats, head_revenue, zh),
        _coverage_tile(coverage_stats, zh),
        tile("追踪子类目" if zh else "Tracked sub-categories", str(len(board)),
             ("家具 / 户外 / 办公 三个部门，按月遍历自动纳入" if zh
              else "furniture, patio and office, enrolled by the monthly walk"),
             observed=True),
        tile("类目均价中位" if zh else "Median category price",
             money(scoring._median([r["median_price"] for r in board])),
             ("售价是挂牌实测值，不经建模" if zh
              else "price is read off the listing, not modelled"),
             observed=True),
        tile("最佳机会类目" if zh else "Top opportunity",
             board[0]["label"] if board else "—",
             f"{board[0]['category_score']}/100" if board else "",
             computed=True),
        tile("高价值机会信号" if zh else "High-value openings",
             str(watch["counts"]["opportunity_high"]),
             f"{watch['counts']['opportunity_total']} " + ("条机会" if zh else "openings"),
             computed=True),
        tile("高风险信号" if zh else "High-severity risks",
             str(watch["counts"]["risk_high"]),
             f"{watch['counts']['risk_total']} " + ("条风险" if zh else "risks"),
             computed=True),
        _return_risk_tile(board, zh),
    ]

    return {
        "headline": {"kpis": filled(kpis)},
        "coverage_stats": coverage_stats,
        "board": board,
        "monitor": watch,
        "movers": {"rising": rising, "declining": declining},
        # The opportunity quadrant. It used to plot one dot per category, which
        # is a chart of thirteen rows the board already lists — and it could
        # only draw the categories whose growth happened to be measurable, so it
        # was both a duplicate and an incomplete one. A point here is a spec:
        # room, shelf, colour and look, read off the listings that carry it.
        "spec_map": _spec_map(
            elements.category_specs(
                mining.products, element_rows,
                {n["node_id_path"]: n for n in taxonomy.leaf_nodes(marketplace)},
                before=mining.products_before),
            board, zh, window=(mining.before_period, period)),
        "treemap": [{"node_key": r["node_key"], "label": r["label"],
                     "value": r["covered_revenue"] or r["revenue_est"] or 0.0,
                     "growth_pct": r["growth_pct"],
                     "growth_from": r["growth_from"], "growth_to": r["growth_to"],
                     "score": r["category_score"]}
                    for r in board if (r["revenue_est"] or 0) > 0],
        "trend": _department_trend(histories, board),
        "price": _overview_price_bands(marketplace, period, board),
        "concentration": [{"node_key": r["node_key"], "label": r["label"],
                           "top5_brand_share_pct": r["top5_brand_share_pct"],
                           "top10_brand_share_pct":
                               pct((snapshots.get(r["node_key"]) or {}).get("top10_brand_crn")),
                           "top5_seller_share_pct":
                               pct((snapshots.get(r["node_key"]) or {}).get("top5_seller_crn")),
                           "top5_product_share_pct":
                               pct((snapshots.get(r["node_key"]) or {}).get("top5_product_crn"))}
                          for r in board if r["top5_brand_share_pct"] is not None],
        "physical": _physical_rows(board, snapshots),
        # The curve the price factor was actually scored against, so a reader can
        # see what "price fit" means this month instead of taking it on faith.
        "price_fit": scoring.price_curve_rows(aov_curve),
        "elements": element_rows,
        # The spec chart reads the same mined vocabulary back off the listings,
        # so it needs the named terms rather than the per-term aggregates — and
        # the same inputs the mining used, not a second read of them.
        "element_combos": _combo_matrix(
            elements.combinations(mining.products, element_rows, mining.phrases,
                                  previous=mining.before),
            zh),
        "follow": _follow(board, rising_elements, zh),
        "avoid": _avoid(board, falling_elements, zh),
        "supply": _supply_rows(board, snapshots),
        "fulfilment": _fulfilment_rows(board, snapshots),
        "quality": _quality_rows(board, snapshots),
        "conversion": _conversion_rows(board, snapshots),
        "newproduct": _newproduct_rows(board, snapshots),
        "returnrisk": [{"node_key": r["node_key"], "label": r["label"],
                        "return_ratio_pct": r["return_ratio_pct"],
                        "return_ratio_avg_pct": r["return_ratio_avg_pct"],
                        "return_risk": r["return_risk"]} for r in board
                       if r["return_ratio_pct"] is not None],
        "coverage": families,
    }


def _coverage_totals(board: Sequence[dict]) -> dict:
    """What the summed-ASIN roll-up actually covers, across the tracked nodes."""
    revenue = [scoring._num(r.get("covered_revenue")) for r in board]
    revenue = [v for v in revenue if v is not None]
    asins = sum(int(r.get("covered_asins") or 0) for r in board)
    pool = [scoring._num(r.get("product_pool")) for r in board]
    pool = [v for v in pool if v is not None]
    tails = [scoring._num(r.get("product_tail_pct")) for r in board]
    tails = [v for v in tails if v is not None]
    return {
        "revenue": round(sum(revenue), 2) if revenue else None,
        "asins": asins,
        "pool": int(sum(pool)) if pool else None,
        # The worst case across the board: the category whose tail was still
        # paying when collection stopped. An average would let one exhausted
        # category cover for one that got truncated at the page cap.
        "tail_pct": round(max(tails), 2) if tails else None,
        "nodes_with_products": len([r for r in board if (r.get("covered_asins") or 0) > 0]),
    }


def _revenue_tile(stats: Mapping[str, Any], head_revenue: float | None,
                  zh: bool) -> dict:
    """The roll-up, stated as what it is.

    Two caveats were previously merged into one "估算" chip and one hint, which
    made them read as a single hedge about freshness. They are different and both
    permanent: the vendor *models* every money figure from BSR (Amazon publishes
    category revenue to nobody), and this sum covers the ASINs collected rather
    than the whole shelf. The chip carries the first; the hint carries the second;
    the tile beside it carries the coverage itself.
    """
    covered = stats.get("revenue")
    if covered is None:
        return tile("追踪类目月销售额" if zh else "Tracked-category revenue",
                    money(head_revenue) if head_revenue is not None else "—",
                    ("按厂商头部口径；ASIN 明细未采集" if zh
                     else "vendor head-listing basis; per-ASIN rows not collected")
                    if head_revenue is not None
                    else ("本期未取到销售额" if zh else "not collected"),
                    estimated=True)
    return tile("追踪类目月销售额" if zh else "Tracked-category revenue",
                money(covered),
                # Why it is modelled, not whether the month has finished. A closed
                # month does not turn a BSR inference into a measurement.
                ("逐条 ASIN 求和。销量与销售额由厂商按 BSR 推算 —— "
                 "亚马逊不向任何人公开类目销售额，月份结不结束都一样" if zh
                 else "summed row by row. Units and revenue are the vendor's model "
                      "over BSR — Amazon publishes category revenue to nobody, "
                      "closed month or not"),
                estimated=True)


def _coverage_tile(stats: Mapping[str, Any], zh: bool) -> dict:
    """How deep the roll-up went, stated as economics rather than as a fraction.

    This used to read ``2,016 / 505,758`` — listings collected over the listing
    count the vendor reports. Both halves are counts, so the ratio answers "how
    many rows did we read", while the tile is titled for revenue. Those are very
    different numbers, because the rows arrive in revenue order: the top 2,000
    listings of a category hold most of its money and a sliver of its listings.

    A true revenue-coverage ratio cannot be shown at all — nobody publishes the
    denominator. Amazon does not, and the vendor's own category total covers only
    the ~100 head listings it analyses. So the statement is the one the data
    supports: how many listings were summed, and what the last page was worth.
    """
    asins = stats.get("asins") or 0
    if not asins:
        return tile("已采集 listing" if zh else "Listings summed", "—",
                    "本期未采集 ASIN 明细" if zh else "no ASIN rows collected")
    tail = scoring._num(stats.get("tail_pct"))
    if tail is None:
        hint = "逐条求和" if zh else "summed row by row"
    elif tail < jobs.PRODUCT_TAIL_PCT:
        hint = (f"已采到尾部无量（边际页仅贡献 {tail:.1f}%）" if zh
                else f"paged until a page added {tail:.1f}% — the tail is spent")
    else:
        hint = (f"触及页数上限，最深类目边际页仍贡献 {tail:.1f}%" if zh
                else f"hit the page cap; the deepest category's last page still "
                     f"added {tail:.1f}%")
    return tile("已采集 listing" if zh else "Listings summed", f"{asins:,}", hint,
                observed=True)


def _return_risk_tile(board: Sequence[dict], zh: bool) -> dict:
    """How many categories return worse than their peers — out of how many we know.

    Counting only the rows that cleared the comparison made a month with no return
    data read as "zero categories at risk", which is the most reassuring possible
    way to say "we have no idea". The denominator is the honest part.
    """
    known = [r for r in board if r["return_ratio_pct"] is not None
             and r["return_ratio_avg_pct"] is not None]
    if not known:
        return tile("退货率高于同级的类目" if zh else "Above-average return risk", "—",
                    "本期未取到退货率" if zh else "return rate not collected")
    worse = [r for r in known if r["return_ratio_pct"] > r["return_ratio_avg_pct"]]
    if len(known) == len(board):
        # Every tracked category answered, so the denominator is the board itself
        # and printing it says nothing. A fraction is for reporting a gap.
        return tile("退货率高于同级的类目" if zh else "Above-average return risk",
                    str(len(worse)),
                    (f"{len(known)} 个类目全部已取到退货率" if zh
                     else f"all {len(known)} categories have a known rate"),
                    observed=True)
    return tile("退货率高于同级的类目" if zh else "Above-average return risk",
                f"{len(worse)} / {len(known)}",
                (f"仅 {len(known)}/{len(board)} 个类目取到退货率" if zh
                 else f"only {len(known)} of {len(board)} have a known rate"),
                observed=True)


def _department_trend(histories: Mapping[str, Sequence[dict]],
                      board: Sequence[dict]) -> list[dict]:
    """Furniture-wide revenue by month, summed across the tracked leaves.

    The department roll-up row would be the obvious source, but it only exists
    for months the sweep actually reached; summing the leaves gives a line that
    survives a month where only the roll-up job was skipped.
    """
    keys = {row["node_key"] for row in board}
    totals: dict[str, float] = {}
    for path, history in histories.items():
        if path not in keys:
            continue
        for point in history:
            value = scoring._num(point.get("total_revenue"))
            if value is None:
                continue
            totals[str(point.get("period"))] = totals.get(str(point.get("period")), 0.0) + value
    return [{"period": key, "value": round(totals[key], 2)} for key in sorted(totals)]


def _supply_rows(board: Sequence[dict], snapshots: Mapping[str, dict]) -> list[dict]:
    rows = []
    for row in board:
        snap = snapshots.get(row["node_key"]) or {}
        if snap.get("total_products") is None and snap.get("sellers") is None:
            continue
        rows.append({
            "node_key": row["node_key"], "label": row["label"],
            "products": snap.get("total_products"),
            "sellers": snap.get("sellers"),
            "brands": snap.get("brands"),
            "avg_sellers": snap.get("avg_sellers"),
            # Revenue per listing is the crowding measure that matters: a category
            # can add listings all year without the money following them.
            "revenue_per_listing": (
                (scoring._num(snap.get("total_revenue")) or 0.0)
                / scoring._num(snap.get("total_products"))
                if scoring._num(snap.get("total_products")) else None),
        })
    return rows


def _fulfilment_rows(board: Sequence[dict], snapshots: Mapping[str, dict]) -> list[dict]:
    rows = []
    for row in board:
        snap = snapshots.get(row["node_key"]) or {}
        if snap.get("fba_proportion") is None and snap.get("amazon_self_proportion") is None:
            continue
        rows.append({
            "node_key": row["node_key"], "label": row["label"],
            "fba_pct": pct(snap.get("fba_proportion")),
            "fbm_pct": pct(snap.get("fbm_proportion")),
            "amazon_self_pct": pct(snap.get("amazon_self_proportion")),
            "ebc_pct": pct(snap.get("ebc_proportion")),
        })
    return rows


def _quality_rows(board: Sequence[dict], snapshots: Mapping[str, dict]) -> list[dict]:
    rows = []
    for row in board:
        snap = snapshots.get(row["node_key"]) or {}
        if snap.get("avg_rating") is None:
            continue
        rows.append({
            "node_key": row["node_key"], "label": row["label"],
            "avg_rating": snap.get("avg_rating"),
            "avg_ratings": snap.get("avg_ratings"),
            "head_avg_ratings": snap.get("hl_avg_ratings"),
            "head_avg_price": snap.get("hl_avg_price"),
        })
    return rows


def _conversion_rows(board: Sequence[dict], snapshots: Mapping[str, dict]) -> list[dict]:
    rows = []
    for row in board:
        snap = snapshots.get(row["node_key"]) or {}
        if snap.get("search_purchase_ratio") is None and snap.get("glance_views") is None:
            continue
        rows.append({
            "node_key": row["node_key"], "label": row["label"],
            "search_purchase_ratio": snap.get("search_purchase_ratio"),
            "search_purchase_ratio_avg": snap.get("search_purchase_ratio_avg"),
            "glance_views": snap.get("glance_views"),
        })
    return rows


def _newproduct_rows(board: Sequence[dict], snapshots: Mapping[str, dict]) -> list[dict]:
    rows = []
    for row in board:
        snap = snapshots.get(row["node_key"]) or {}
        rows.append({
            "node_key": row["node_key"], "label": row["label"],
            "new_revenue_share_pct": row["new_revenue_share_pct"],
            "new_count_l12": snap.get("new_count_l12"),
            "new_ratio_l12_pct": pct(snap.get("new_ratio_l12")),
            "new_ratio_l6_pct": pct(snap.get("new_ratio_l6")),
            "new_avg_revenue_l12": snap.get("new_avg_revenue_l12"),
            # The number that decides whether the window is real: a newcomer's
            # review count is the wall a new listing has to climb.
            "new_avg_reviews_l12": snap.get("new_avg_reviews_l12"),
            "completeness": row["completeness"],
        })
    return rows


def _physical_rows(board: Sequence[dict], snapshots: Mapping[str, dict]) -> list[dict]:
    """Each tracked category as a physical object, ranked by price density.

    ``price_per_lb`` is the whole point of the row. Freight and the cost of a
    return scale with weight while the price does not, so two categories with the
    same revenue and the same growth can have opposite economics — and nothing
    else on this board would show it.
    """
    rows = []
    for row in board:
        snap = snapshots.get(row["node_key"]) or {}
        weight = scoring._num(snap.get("avg_weight"))
        price = scoring._num(snap.get("avg_price"))
        if weight is None and price is None:
            continue
        rows.append({
            "node_key": row["node_key"], "label": row["label"],
            "avg_weight": round(weight, 1) if weight is not None else None,
            "avg_volume": scoring._num(snap.get("avg_volume")),
            "avg_price": price,
            "price_per_lb": (round(price / weight, 2)
                             if price is not None and weight else None),
            "return_ratio_pct": row.get("return_ratio_pct"),
            "return_ratio_avg_pct": row.get("return_ratio_avg_pct"),
        })
    # Best freight economics first: the row a product decision starts from.
    rows.sort(key=lambda r: (r["price_per_lb"] is None, -(r["price_per_lb"] or 0.0)))
    return rows


def _overview_price_bands(marketplace: str, period: str,
                          board: Sequence[dict]) -> list[dict]:
    """Price bands summed across the tracked nodes, weighted by their revenue."""
    totals: dict[str, dict] = {}
    for row in board:
        for bucket in store.get_distribution(marketplace, row["node_key"], period, "price"):
            entry = totals.setdefault(bucket["bucket_key"],
                                      {"bucket_key": bucket["bucket_key"],
                                       "products": 0.0, "units": 0.0, "revenue": 0.0,
                                       "order": bucket["bucket_order"]})
            entry["products"] += bucket.get("products") or 0.0
            entry["units"] += bucket.get("units") or 0.0
            entry["revenue"] += bucket.get("revenue") or 0.0
    bands = sorted(totals.values(), key=lambda b: b["order"])
    revenue_total = sum(b["revenue"] for b in bands) or 1.0
    product_total = sum(b["products"] for b in bands) or 1.0
    for band in bands:
        band["revenue_share_pct"] = round(band["revenue"] / revenue_total * 100.0, 1)
        band["listing_share_pct"] = round(band["products"] / product_total * 100.0, 1)
    return bands


# ----------------------------------------------------------------- category ----

def build_category(marketplace: str, node_id_path: str, period: str,
                   language: str) -> dict:
    """Every deterministic section of one category deep dive."""
    zh = _zh(language)
    snap = store.get_node_snapshot(marketplace, node_id_path, period) or {}
    history = store.snapshot_history(marketplace, node_id_path)
    keywords = store.top_keywords(marketplace, node_id_path, period, limit=MAX_KEYWORDS)
    products = store.top_products(marketplace, node_id_path, period, limit=MAX_COMPETITORS)
    themes = store.review_themes(marketplace, node_id_path, period)
    distributions = store.all_distributions(marketplace, node_id_path, period)
    concentration = store.all_concentration(marketplace, node_id_path, period)
    trend_index = store.keyword_series(marketplace, node_id_path)
    aov_curve = price_curve(marketplace, period)
    score = scoring.score_category(snap, history=history, keywords=keywords,
                                   aov_curve=aov_curve)
    completeness, missing = jobs.node_completeness(marketplace, node_id_path, period)
    label = taxonomy.label_for(node_id_path, marketplace)

    siblings = store.list_node_snapshots(marketplace, period)
    peers = _with_product_peers(monitor.peer_medians(
        [s for s in siblings if s["node_id_path"] != taxonomy.FURNITURE_ROOT],
        {s["node_id_path"]: store.snapshot_history(marketplace, s["node_id_path"])
         for s in siblings if s["node_id_path"] != taxonomy.FURNITURE_ROOT}),
        marketplace, period)
    facts = monitor.NodeFacts(
        node_key=node_id_path, label=taxonomy.short_label(label), snapshot=snap,
        history=history, keywords=keywords, products=products, themes=themes,
        distributions=distributions, concentration=concentration,
        trend_index=trend_index, peers=peers)
    watch = monitor.split(monitor.rank(alerts_for(facts, marketplace, period, language)),
                          limit=monitor.MAX_ALERTS_PER_NODE)

    opportunities = []
    for product in products[:MAX_OPPORTUNITIES]:
        product_score = scoring.score_product(
            product, snapshot=snap, history=history, keywords=keywords, pain=themes,
            aov_curve=aov_curve)
        opportunities.append({
            "id": f"{node_id_path}|{product['asin']}|{period}",
            "anchor_asin": product["asin"],
            "title": (product.get("title") or product["asin"])[:80],
            "product_score": product_score["score"],
            "score_breakdown": product_score["breakdown"],
            "score_confidence": product_score["confidence"],
            "score_missing": product_score["missing"],
            "price": product.get("price"),
            "revenue_est": product.get("revenue"),
            "ratings": product.get("ratings"),
            "rating": product.get("rating"),
        })
    opportunities.sort(key=lambda o: o["product_score"], reverse=True)

    traffic = [{"asin": p["asin"], "title": (p.get("title") or "")[:60],
                "natural": p.get("natural_proportion"), "ad": p.get("ad_proportion"),
                "recommendation": p.get("recommendation_proportion")}
               for p in products if p.get("natural_proportion") is not None]

    return {
        "header": {
            "node_key": node_id_path,
            "node_label_path": label,
            "label": taxonomy.short_label(label),
            "category_score": score["score"],
            "score_breakdown": score["breakdown"],
            "score_confidence": score["confidence"],
            "score_missing": score["missing"],
            "completeness": completeness,
            "missing": missing,
            "kpis": filled(_category_kpis(snap, zh)),
        },
        "monitor": watch,
        "structure": {
            "price_bands": distributions.get("price", []),
            "listing_dates": distributions.get("listing_date", []),
            "brands": concentration.get("brand", [])[:10],
            "trend": [{"period": p["period"], "value": p.get("total_revenue")}
                      for p in history if p.get("total_revenue") is not None],
            "glance_views": [{"period": p["period"], "value": p.get("glance_views")}
                             for p in history if p.get("glance_views") is not None],
        },
        "spec": _spec_envelope(snap, products, zh),
        "distributions": _distribution_panels(distributions, zh),
        "concentration": _concentration_panels(concentration, zh),
        "benchmark": _benchmark(snap, history, peers, zh),
        "fulfilment": {
            "fba_pct": pct(snap.get("fba_proportion")),
            "fbm_pct": pct(snap.get("fbm_proportion")),
            "amazon_self_pct": pct(snap.get("amazon_self_proportion")),
            "ebc_pct": pct(snap.get("ebc_proportion")),
        },
        "supply": {
            "products": snap.get("total_products"),
            "sellers": snap.get("sellers"),
            "brands": snap.get("brands"),
            "avg_sellers": snap.get("avg_sellers"),
            "avg_volume": snap.get("avg_volume"),
            "avg_weight": snap.get("avg_weight"),
        },
        "conversion": {
            "search_purchase_ratio": snap.get("search_purchase_ratio"),
            "search_purchase_ratio_avg": snap.get("search_purchase_ratio_avg"),
            "glance_views": snap.get("glance_views"),
        },
        "offamazon": [{"period": row["period"], "value": row["value"],
                       "keyword": row.get("keyword")} for row in trend_index],
        "history": _asin_history(marketplace, products),
        "keyword_edges": _keyword_edges(marketplace, period, products),
        "keywords": keywords,
        "competitors": products,
        "pain": themes,
        "traffic": traffic,
        "opportunities": opportunities,
    }


def _spec_envelope(snap: Mapping[str, Any], products: Sequence[Mapping[str, Any]],
                   zh: bool) -> dict:
    """The physical envelope a new product would have to fit inside.

    Every figure here is a decision an engineer makes before a drawing exists:
    how heavy, how bulky, how many variants, who fulfils it. The vendor returns
    all of it with calls the sweep already makes — ``avgWeight`` / ``avgVolume``
    on ``market_research``, ``weight`` / ``dimension`` / ``variations`` on every
    ``product_research`` row — and until now it sat in the warehouse unread while
    the dashboard led with traffic mix.

    Medians rather than means: one 400 lb sectional in a set of ten drags a mean
    somewhere no real product sits.
    """
    weights = [scoring._num(p.get("weight")) for p in products]
    variations = [scoring._num(p.get("variations")) for p in products]
    prices = [scoring._num(p.get("price")) for p in products]
    head_weight = scoring._median([w for w in weights if w is not None])
    head_variations = scoring._median([v for v in variations if v is not None])

    rows = []
    for product in products[:MAX_COMPETITORS]:
        weight = scoring._num(product.get("weight"))
        rows.append({
            "asin": product["asin"],
            "title": (product.get("title") or "")[:70],
            "price": scoring._num(product.get("price")),
            "weight": round(weight, 1) if weight is not None else None,
            "dimension": product.get("dimension") or "",
            "variations": scoring._num(product.get("variations")),
            "fulfillment": product.get("fulfillment") or "",
        })

    return {
        "tiles": filled([
            tile("货架平均重量" if zh else "Shelf average weight",
                 f"{round(scoring._num(snap.get('avg_weight')), 1)} lb"
                 if scoring._num(snap.get("avg_weight")) is not None else "",
                 "决定运费档、破损率和退货成本" if zh
                 else "sets the freight tier, damage rate and return cost"),
            tile("货架平均体积" if zh else "Shelf average volume",
                 f"{int(scoring._num(snap.get('avg_volume'))):,} in³"
                 if scoring._num(snap.get("avg_volume")) is not None else "",
                 "决定装箱、仓储分档" if zh else "drives cartoning and storage tier"),
            tile("头部重量中位" if zh else "Head-set median weight",
                 f"{round(head_weight, 1)} lb" if head_weight is not None else "",
                 "实际在卖的产品有多重" if zh else "what actually sells, not the long tail"),
            tile("头部变体数中位" if zh else "Head-set median variations",
                 f"{round(head_variations, 1)}" if head_variations is not None else "",
                 "一次要开几个 SKU" if zh else "how many SKUs a launch has to cover"),
            tile("头部价格区间" if zh else "Head-set price range",
                 f"{money(min(p for p in prices if p is not None))}–"
                 f"{money(max(p for p in prices if p is not None))}"
                 if any(p is not None for p in prices) else "",
                 "新品定价要落在这里面" if zh else "a new product has to price into this"),
        ]),
        "rows": [r for r in rows if r["weight"] is not None or r["dimension"]
                 or r["variations"] is not None],
    }


def _category_kpis(snap: Mapping[str, Any], zh: bool) -> list[dict]:
    new_share = scoring.new_revenue_share_pct(dict(snap))
    return [
        tile("类目月销售额" if zh else "Category revenue",
             money(snap.get("total_revenue")),
             ("厂商按 BSR 推算，且只覆盖它分析的约 100 个头部链接" if zh
              else "the vendor's BSR model, over the ~100 head listings it analyses"),
             estimated=True),
        tile("均价" if zh else "Average price", money(snap.get("avg_price")),
             "新品定价的锚，挂牌实测值" if zh
             else "the anchor a new product prices against; read off the listing",
             observed=True),
        tile("平均重量 / 体积" if zh else "Average weight / volume",
             f"{round(scoring._num(snap.get('avg_weight')), 1)} lb / "
             f"{int(scoring._num(snap.get('avg_volume'))):,} in³"
             if scoring._num(snap.get("avg_weight")) is not None
             and scoring._num(snap.get("avg_volume")) is not None
             else (f"{round(scoring._num(snap.get('avg_weight')), 1)} lb"
                   if scoring._num(snap.get("avg_weight")) is not None else "—"),
             "运费档与破损率的上游" if zh else "upstream of freight tier and damage rate",
             observed=True),
        tile("退货率 / 同级均值" if zh else "Return rate vs peers",
             f"{pct(snap.get('return_ratio'))}% / {pct(snap.get('return_ratio_avg'))}%"
             if snap.get("return_ratio") is not None else "—",
             "一次货运退货吃掉整单毛利" if zh
             else "one freight return costs more than the order's margin",
             observed=True),
        tile("类目均分" if zh else "Average rating",
             f"{snap.get('avg_rating')}★" if snap.get("avg_rating") is not None else "—",
             f"{'头部评论数' if zh else 'head reviews'} {int(snap['hl_avg_ratings'])}"
             if scoring._num(snap.get("hl_avg_ratings")) else "",
             observed=True),
        tile("在售 / 卖家 / 品牌" if zh else "Listings / sellers / brands",
             " / ".join(str(int(v)) if v is not None else "—"
                        for v in (scoring._num(snap.get("total_products")),
                                  scoring._num(snap.get("sellers")),
                                  scoring._num(snap.get("brands"))))
             if any(snap.get(k) is not None
                    for k in ("total_products", "sellers", "brands")) else "—",
             observed=True),
        tile("Top5 品牌集中度" if zh else "Top-5 brand share",
             f"{pct(snap.get('top5_brand_crn'))}%"
             if snap.get("top5_brand_crn") is not None else "—",
             ("按销售额算，所以继承销售额的建模口径" if zh
              else "computed on revenue, so it inherits the revenue model"),
             estimated=True),
        tile("近 12 月新品占销额" if zh else "New-entrant revenue share",
             f"{round(new_share, 1)}%" if new_share is not None else "—",
             ("新品数 × 新品均销额 ÷ 类目销额，三项都来自厂商的销量模型" if zh
              else "new count x new average revenue over category revenue; all "
                   "three come from the vendor's volume model"),
             estimated=True),
        tile("FBA / 亚马逊自营" if zh else "FBA / Amazon-self",
             f"{pct(snap.get('fba_proportion')) or '—'}% / "
             f"{pct(snap.get('amazon_self_proportion')) or '—'}%"
             if snap.get("fba_proportion") is not None else "—",
             observed=True),
    ]


# The rotating collector buys one of these per flagship per month, so which
# panels exist varies. Rendering only what arrived beats four empty charts.
_DISTRIBUTION_LABELS: dict[str, tuple[str, str]] = {
    "price": ("价格带", "Price band"),
    "listing_date": ("上架时间", "Listing age"),
    "rating": ("评分", "Rating"),
    "ratings_count": ("评论数", "Review count"),
    "ebc": ("A+ 内容", "A+ content"),
    "seller_country": ("卖家国别", "Seller country"),
    "listing_trend": ("上架趋势", "Listing trend"),
}

_CONCENTRATION_LABELS: dict[str, tuple[str, str]] = {
    "brand": ("品牌", "Brand"),
    "seller": ("卖家", "Seller"),
    "seller_type": ("卖家类型", "Seller type"),
    "product": ("商品", "Product"),
    "seller_country": ("卖家国别", "Seller country"),
}


def _distribution_panels(distributions: Mapping[str, Sequence[dict]],
                         zh: bool) -> list[dict]:
    out = []
    for kind, buckets in distributions.items():
        if kind in ("price", "listing_date") or not buckets:
            continue  # already shown in the structure section
        names = _DISTRIBUTION_LABELS.get(kind, (kind, kind))
        out.append({
            "kind": kind,
            "label": names[0] if zh else names[1],
            "buckets": [{"bucket_key": b["bucket_key"],
                         "products": b.get("products"),
                         "products_pct": pct(b.get("products_ratio")),
                         "revenue_pct": pct(b.get("revenue_ratio")),
                         "units_pct": pct(b.get("units_ratio"))}
                        for b in buckets],
        })
    return out


def _concentration_panels(concentration: Mapping[str, Sequence[dict]],
                          zh: bool) -> list[dict]:
    out = []
    for kind, entities in concentration.items():
        if kind == "brand" or not entities:
            continue  # already shown in the structure section
        names = _CONCENTRATION_LABELS.get(kind, (kind, kind))
        out.append({
            "kind": kind,
            "label": names[0] if zh else names[1],
            "entities": [{"entity": e["entity"], "rank": e.get("rank"),
                          "revenue_pct": pct(e.get("revenue_ratio")),
                          "units_pct": pct(e.get("units_ratio")),
                          "products": e.get("products"),
                          "rating": e.get("rating")}
                         for e in entities[:8]],
        })
    return out


def _benchmark(snap: Mapping[str, Any], history: Sequence[dict],
               peers: Mapping[str, float | None], zh: bool) -> list[dict]:
    """This node against the department median, on one comparable scale.

    Each axis is the node's value as a share of twice the median, so 50 means
    parity and the shape — not any single spoke — is the reading. Axes where the
    node is *better when lower* (returns, concentration) are inverted here so
    that outward always means better; a radar where some spokes mean the
    opposite of others cannot be read at a glance.
    """
    def axis(key: str, value: float | None, *, invert: bool = False) -> dict | None:
        peer = peers.get(key)
        if value is None or peer in (None, 0):
            return None
        ratio = value / peer
        if invert:
            ratio = (2.0 - ratio) if ratio <= 2.0 else 0.0
        return {"key": key, "value": value, "peer": peer,
                "score": round(scoring.clamp(ratio * 50.0), 1)}

    growth = scoring.growth_pct(history)
    growth_peer = peers.get("revenue_growth_pct")
    rows = [
        axis("total_revenue", scoring._num(snap.get("total_revenue"))),
        axis("avg_price", scoring._num(snap.get("avg_price"))),
        axis("avg_rating", scoring._num(snap.get("avg_rating"))),
        axis("top5_brand_crn", scoring._num(snap.get("top5_brand_crn")), invert=True),
        axis("return_ratio", scoring._num(snap.get("return_ratio")), invert=True),
        axis("new_ratio_l12", scoring._num(snap.get("new_ratio_l12"))),
    ]
    if growth is not None and growth_peer is not None:
        # Growth is already a percentage and can be negative, so the ratio trick
        # does not apply: shift both sides onto a 0-100 scale around zero.
        rows.append({"key": "revenue_growth_pct", "value": growth, "peer": growth_peer,
                     "score": round(scoring.clamp(50.0 + (growth - growth_peer) * 2.0), 1)})

    labels = {
        "total_revenue": ("需求规模", "Demand"),
        "avg_price": ("客单价", "Price"),
        "avg_rating": ("满意度", "Satisfaction"),
        "top5_brand_crn": ("格局分散度", "Fragmentation"),
        "return_ratio": ("退货优势", "Return edge"),
        "new_ratio_l12": ("新品活跃度", "Newcomer activity"),
        "revenue_growth_pct": ("增长", "Growth"),
    }
    out = []
    for row in rows:
        if row is None:
            continue
        names = labels.get(row["key"], (row["key"], row["key"]))
        out.append({**row, "label": names[0] if zh else names[1]})
    return out


def _asin_history(marketplace: str, products: Sequence[dict]) -> list[dict]:
    """The 14-month series ``asin_prediction`` already bought, per head ASIN.

    One call carries fourteen months, so this is the cheapest long series in the
    warehouse and it was going unrendered.
    """
    out = []
    for product in products[:MAX_HISTORY_ASINS]:
        units = store.product_history(marketplace, product["asin"], "units")
        revenue = store.product_history(marketplace, product["asin"], "revenue")
        if not units and not revenue:
            continue
        out.append({
            "asin": product["asin"],
            "title": (product.get("title") or "")[:60],
            "units": [{"period": p["period"], "value": p["value"]} for p in units],
            "revenue": [{"period": p["period"], "value": p["value"]} for p in revenue],
        })
    return out


def _keyword_edges(marketplace: str, period: str,
                   products: Sequence[dict]) -> list[dict]:
    """Which phrases actually carry traffic into the head listings.

    Distinct from the keyword table above: that one is market-wide demand, this
    one is the proven route into a specific competitor. The overlap between them
    is where a new listing can realistically rank.
    """
    out = []
    for product in products[:MAX_EDGE_ASINS]:
        edges = store.keyword_edges(marketplace, product["asin"], period, limit=12)
        if not edges:
            continue
        out.append({
            "asin": product["asin"],
            "title": (product.get("title") or "")[:60],
            "edges": [{"keyword": e["keyword"],
                       "traffic_pct": e.get("traffic_percentage"),
                       "natural_ratio": e.get("natural_ratio"),
                       "ad_ratio": e.get("ad_ratio"),
                       "searches": e.get("searches"),
                       "natural_rank": e.get("natural_rank"),
                       "ad_position": e.get("ad_position")}
                      for e in edges],
        })
    return out
