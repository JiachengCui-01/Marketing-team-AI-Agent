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

from typing import Any, Mapping, Sequence

from . import gateway, jobs, monitor, scoring, store, taxonomy

MAX_BOARD_ROWS = 24
MAX_COMPETITORS = 12
MAX_KEYWORDS = 25
MAX_OPPORTUNITIES = 4
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


def tile(label: str, value: str, hint: str = "", estimated: bool = False) -> dict:
    return {"label": label, "value": value, "hint": hint, "estimated": estimated}


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

def build_overview(marketplace: str, period: str, language: str) -> dict:
    """Every deterministic section of the discovery board."""
    zh = _zh(language)
    snapshots = {s["node_id_path"]: s for s in store.list_node_snapshots(marketplace, period)}
    histories = {path: store.snapshot_history(marketplace, path)
                 for path in snapshots}
    leaf_snapshots = [snapshots[n["node_id_path"]] for n in taxonomy.leaf_nodes(marketplace)
                      if n["node_id_path"] in snapshots]
    peers = monitor.peer_medians(
        leaf_snapshots,
        {path: history for path, history in histories.items()
         if path != taxonomy.FURNITURE_ROOT})

    totals = store.product_totals(marketplace, period)
    board: list[dict] = []
    alerts: list[dict] = []
    for node in taxonomy.leaf_nodes(marketplace):
        path = node["node_id_path"]
        snap = snapshots.get(path)
        if not snap:
            continue
        history = histories.get(path, [])
        keywords = store.top_keywords(marketplace, path, period, limit=20)
        score = scoring.score_category(snap, history=history, keywords=keywords)
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
            "revenue_est": snap.get("total_revenue"),
            # The wider figure: every ASIN row we hold for this node, summed.
            "covered_revenue": (totals.get(path) or {}).get("revenue"),
            "covered_asins": (totals.get(path) or {}).get("asins") or 0,
            "product_pool": snap.get("product_pool"),
            "growth_pct": scoring.growth_pct(history),
            "median_price": snap.get("avg_price"),
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

    kpis = [
        _revenue_tile(coverage_stats, head_revenue, zh),
        _coverage_tile(coverage_stats, zh),
        tile("追踪子类目" if zh else "Tracked sub-categories", str(len(board))),
        tile("最佳机会类目" if zh else "Top opportunity",
             board[0]["label"] if board else "—",
             f"{board[0]['category_score']}/100" if board else ""),
        tile("类目均价中位" if zh else "Median category price",
             money(scoring._median([r["median_price"] for r in board]))),
        tile("高风险信号" if zh else "High-severity risks",
             str(watch["counts"]["risk_high"]),
             f"{watch['counts']['risk_total']} " + ("条风险" if zh else "risks")),
        tile("高价值机会信号" if zh else "High-value openings",
             str(watch["counts"]["opportunity_high"]),
             f"{watch['counts']['opportunity_total']} " + ("条机会" if zh else "openings")),
        _return_risk_tile(board, zh),
        tile("已覆盖数据类型" if zh else "Vendor data families",
             f"{families['present']}/{families['total']}"),
    ]

    return {
        "headline": {"kpis": filled(kpis)},
        "coverage_stats": coverage_stats,
        "board": board,
        "monitor": watch,
        "movers": {"rising": rising, "declining": declining},
        "map": [{"node_key": r["node_key"], "label": r["label"],
                 "competition": 100.0 - (r["top5_brand_share_pct"] or 0.0),
                 "growth_pct": r["growth_pct"], "revenue_est": r["revenue_est"],
                 "return_risk": r["return_risk"]} for r in board],
        "treemap": [{"node_key": r["node_key"], "label": r["label"],
                     "value": r["covered_revenue"] or r["revenue_est"] or 0.0,
                     "growth_pct": r["growth_pct"],
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
    return {
        "revenue": round(sum(revenue), 2) if revenue else None,
        "asins": asins,
        "pool": int(sum(pool)) if pool else None,
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
                ("已采集 ASIN 逐条求和，非厂商头部口径" if zh
                 else "summed from the collected ASIN rows, not the vendor head total"),
                estimated=True)


def _coverage_tile(stats: Mapping[str, Any], zh: bool) -> dict:
    """How much of the shelf that roll-up actually saw.

    A roll-up without its denominator invites being read as the whole market,
    which is exactly the mistake the old headline made.
    """
    asins, pool = stats.get("asins") or 0, stats.get("pool")
    if not asins:
        return tile("销售额覆盖" if zh else "Revenue coverage", "—",
                    "本期未采集 ASIN 明细" if zh else "no ASIN rows collected")
    if not pool:
        return tile("销售额覆盖" if zh else "Revenue coverage",
                    f"{asins:,}",
                    "个已采集 ASIN" if zh else "ASINs collected")
    return tile("销售额覆盖" if zh else "Revenue coverage",
                f"{asins:,} / {pool:,}",
                ("已采集 ASIN / 厂商报告的在售数" if zh
                 else "ASINs collected / listings the vendor reports"))


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
    return tile("退货率高于同级的类目" if zh else "Above-average return risk",
                f"{len(worse)} / {len(known)}",
                ("已知退货率的类目" if zh else "categories with a known rate"))


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
    score = scoring.score_category(snap, history=history, keywords=keywords)
    completeness, missing = jobs.node_completeness(marketplace, node_id_path, period)
    label = taxonomy.label_for(node_id_path, marketplace)

    siblings = store.list_node_snapshots(marketplace, period)
    peers = monitor.peer_medians(
        [s for s in siblings if s["node_id_path"] != taxonomy.FURNITURE_ROOT],
        {s["node_id_path"]: store.snapshot_history(marketplace, s["node_id_path"])
         for s in siblings if s["node_id_path"] != taxonomy.FURNITURE_ROOT})
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
            product, snapshot=snap, history=history, keywords=keywords, pain=themes)
        opportunities.append({
            "id": f"{node_id_path}|{product['asin']}|{period}",
            "anchor_asin": product["asin"],
            "title": (product.get("title") or product["asin"])[:80],
            "product_score": product_score["score"],
            "score_breakdown": product_score["breakdown"],
            "score_confidence": product_score["confidence"],
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


def _category_kpis(snap: Mapping[str, Any], zh: bool) -> list[dict]:
    new_share = scoring.new_revenue_share_pct(dict(snap))
    return [
        tile("类目月销售额" if zh else "Category revenue",
             money(snap.get("total_revenue")),
             ("厂商按头部约 100 个链接建模估算" if zh
              else "vendor model over its ~100 head listings"),
             estimated=True),
        tile("均价" if zh else "Average price", money(snap.get("avg_price"))),
        tile("在售 / 卖家 / 品牌" if zh else "Listings / sellers / brands",
             " / ".join(str(int(v)) if v is not None else "—"
                        for v in (scoring._num(snap.get("total_products")),
                                  scoring._num(snap.get("sellers")),
                                  scoring._num(snap.get("brands"))))
             if any(snap.get(k) is not None
                    for k in ("total_products", "sellers", "brands")) else "—"),
        tile("Top5 品牌集中度" if zh else "Top-5 brand share",
             f"{pct(snap.get('top5_brand_crn'))}%"
             if snap.get("top5_brand_crn") is not None else "—"),
        tile("类目均分" if zh else "Average rating",
             f"{snap.get('avg_rating')}★" if snap.get("avg_rating") is not None else "—",
             f"{'头部' if zh else 'head'} {int(snap['hl_avg_ratings'])}"
             if scoring._num(snap.get("hl_avg_ratings")) else ""),
        tile("退货率 / 同级均值" if zh else "Return rate vs peers",
             f"{pct(snap.get('return_ratio'))}% / {pct(snap.get('return_ratio_avg'))}%"
             if snap.get("return_ratio") is not None else "—"),
        tile("近 12 月新品占销额" if zh else "New-entrant revenue share",
             f"{round(new_share, 1)}%" if new_share is not None else "—",
             estimated=True),
        tile("FBA / 亚马逊自营" if zh else "FBA / Amazon-self",
             f"{pct(snap.get('fba_proportion')) or '—'}% / "
             f"{pct(snap.get('amazon_self_proportion')) or '—'}%"
             if snap.get("fba_proportion") is not None else "—"),
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
