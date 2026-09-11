"""The collection plan: what to fetch, how often, in what order, at what cost.

Category structure is *monthly* data — ``market_research``, every distribution, and
every concentration tool all take a ``month``. Re-fetching them daily buys nothing.
So the primitive here is not "sweep everything today" but **a due-job queue drained
against a daily cap**: a new month opens ~200 jobs, the first days of the month run
flat out, and the rest of the month is nearly idle.

``priority`` is what makes a partial month useful. Structure jobs (20-40) land in the
first 48 hours, so the board is decision-grade almost immediately; enrichment jobs
(60-85) fill in behind them and their absence is reported as a gap rather than
silently rendered as zero.

Per-ASIN jobs are not planned up front — the ASINs are not known until a product
pack lands. ``product_pack`` enqueues them for the tier-1 nodes it just filled.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable

from . import extract, gateway, store, taxonomy
from .evidence import EvidenceIndex
from marketing_agent.tools.mcp_client import McpUnavailable

from .gateway import BudgetExhausted, VendorReply

logger = logging.getLogger(__name__)

# Backoff after a vendor rejection: it is an answer, not an outage, so the job waits
# rather than hammering. Three strikes and the metric becomes a declared gap.
BACKOFF_SECONDS = (3600, 21600, 86400)
MAX_ATTEMPTS = 3

# How many ASINs per tier-1 node get the expensive per-ASIN packs.
FLAGSHIP_ASINS = 2
PRODUCT_PAGE_SIZE = 50
KEYWORD_SEED_BATCH = 10

# The rotating slot: one extra distribution per tier-1 node per month, cycled so the
# full picture is a quarter deep instead of one month wide.
_ROTATION = (
    ("market_seller_type_concentration", "seller_type", "concentration"),
    ("market_ratings_count_distribution", "ratings_count", "distribution"),
    ("market_ebc_distribution", "ebc", "distribution"),
    ("market_seller_country_distribution", "seller_country", "distribution"),
    ("market_rating_distribution", "rating", "distribution"),
)


@dataclass
class JobResult:
    status: str                 # done | pending | blocked | budget
    calls: int = 0
    detail: str = ""
    followups: int = 0


@dataclass(frozen=True)
class JobSpec:
    kind: str
    subject_kind: str
    priority: int
    est_calls: int
    cadence: str                # month | week
    handler: Callable[..., JobResult]
    tier: int | None = None     # None = every tracked node; 1 = flagships only
    scope: str = "node"         # node | department


def _request(**kwargs) -> dict:
    return {"request": {k: v for k, v in kwargs.items() if v is not None}}


def _ok(reply: VendorReply) -> bool:
    return reply.ok


# ------------------------------------------------------------------ handlers ----

def _department_roll(*, marketplace: str, period: str, subject_id: str,
                     bucket: str) -> JobResult:
    """The furniture department's children, ranked by revenue.

    This is the only job that discovers nodes: a sub-category that grew into the
    top of the department should not need a code change to become visible.
    """
    reply = gateway.call(
        "market_research",
        _request(marketplace=marketplace, nodeIdPath=taxonomy.FURNITURE_ROOT,
                 nodeIdPathEqual="false", month=period, size=50,
                 order={"field": "total_amount", "desc": True}),
        bucket=bucket, purpose="department roll-up", marketplace=marketplace,
    )
    if not _ok(reply):
        return JobResult(status="pending", calls=int(reply.billable), detail=reply.detail)

    discovered = 0
    for row in extract.rows(reply):
        path = str(row.get("nodeIdPath") or "").strip()
        label = str(row.get("nodeLabelPath") or "").strip()
        if not path or not taxonomy.is_furniture(label):
            continue
        store.upsert_nodes([{
            "marketplace": marketplace, "node_id_path": path, "node_label_path": label,
            "tracked": path in taxonomy.TRACKED_PATHS,
            "tier": 1 if path in taxonomy.TIER1_PATHS else 2,
            "products": extract.number(row.get("totalProducts")),
            "brand_category": taxonomy.brand_category_for(label),
        }])
        index = EvidenceIndex(marketplace=marketplace, period=period)
        metrics = extract.extract_market_research(reply, node_id_path=path,
                                                  period=period, index=index)
        if metrics:
            store.upsert_node_snapshot(marketplace, path, period, metrics)
            store.record_evidence(index.all_rows())
            discovered += 1
    return JobResult(status="done", calls=int(reply.billable),
                     detail=f"{discovered} category rows")


def _category_structure(*, marketplace: str, period: str, subject_id: str,
                        bucket: str) -> JobResult:
    """``market_research`` + ``market_research_statistics`` for one node.

    Two calls, and between them they carry five of the seven scoring factors:
    concentration, newcomer viability, return rate against the sibling average,
    the price level, and the freight profile.
    """
    calls = 0
    index = EvidenceIndex(marketplace=marketplace, period=period)
    metrics: dict = {}

    reply = gateway.call(
        "market_research",
        _request(marketplace=marketplace, nodeIdPath=subject_id, month=period, size=20,
                 order={"field": "total_amount", "desc": True}),
        bucket=bucket, purpose="category structure", marketplace=marketplace)
    calls += int(reply.billable)
    if _ok(reply):
        metrics.update(extract.extract_market_research(
            reply, node_id_path=subject_id, period=period, index=index))

    stats = gateway.call(
        "market_research_statistics",
        _request(marketplace=marketplace, nodeIdPath=subject_id, month=period, topN=10),
        bucket=bucket, purpose="category statistics", marketplace=marketplace)
    calls += int(stats.billable)
    if _ok(stats):
        # Statistics fills head-listing metrics the roll-up does not carry; where
        # they overlap the roll-up already won, so only new keys are added.
        for key, value in extract.extract_market_statistics(
                stats, node_id_path=subject_id, period=period, index=index).items():
            metrics.setdefault(key, value)

    if not metrics:
        return JobResult(status="pending", calls=calls,
                         detail=reply.detail or stats.detail or "no structure data")
    store.upsert_node_snapshot(marketplace, subject_id, period, metrics)
    store.record_evidence(index.all_rows())
    return JobResult(status="done", calls=calls, detail=f"{len(metrics)} metrics")


def _category_demand(*, marketplace: str, period: str, subject_id: str,
                     bucket: str) -> JobResult:
    """Return rate, search-to-purchase, and page views — with sibling benchmarks."""
    reply = gateway.call(
        "market_product_demand_trend",
        _request(marketplace=marketplace, nodeIdPath=subject_id, month=period),
        bucket=bucket, purpose="category demand", marketplace=marketplace)
    if not _ok(reply):
        return JobResult(status="pending", calls=int(reply.billable), detail=reply.detail)
    index = EvidenceIndex(marketplace=marketplace, period=period)
    metrics, series = extract.extract_demand_trend(
        reply, node_id_path=subject_id, period=period, index=index)
    if metrics:
        store.upsert_node_snapshot(marketplace, subject_id, period, metrics)
    # The series is the trend line; each month lands in its own snapshot row so a
    # 12-month chart survives even when older months were never swept.
    for point in series:
        store.upsert_node_snapshot(marketplace, subject_id, point["period"],
                                   {"glance_views": point["glance_views"]})
    store.record_evidence(index.all_rows())
    return JobResult(status="done", calls=int(reply.billable),
                     detail=f"{len(series)} trend points")


def _distribution_job(tool: str, kind: str):
    def handler(*, marketplace: str, period: str, subject_id: str, bucket: str) -> JobResult:
        reply = gateway.call(
            tool, _request(marketplace=marketplace, nodeIdPath=subject_id, month=period),
            bucket=bucket, purpose=f"{kind} distribution", marketplace=marketplace)
        if not _ok(reply):
            return JobResult(status="pending", calls=int(reply.billable), detail=reply.detail)
        index = EvidenceIndex(marketplace=marketplace, period=period)
        buckets = extract.extract_distribution(reply, kind=kind, node_id_path=subject_id,
                                               period=period, index=index)
        store.replace_distribution(marketplace, subject_id, period, kind, buckets)
        store.record_evidence(index.all_rows())
        return JobResult(status="done", calls=int(reply.billable),
                         detail=f"{len(buckets)} buckets")
    return handler


def _concentration_job(tool: str, kind: str, *, top_n: int | None = 15):
    def handler(*, marketplace: str, period: str, subject_id: str, bucket: str) -> JobResult:
        reply = gateway.call(
            tool, _request(marketplace=marketplace, nodeIdPath=subject_id, month=period,
                           topN=top_n),
            bucket=bucket, purpose=f"{kind} concentration", marketplace=marketplace)
        if not _ok(reply):
            return JobResult(status="pending", calls=int(reply.billable), detail=reply.detail)
        index = EvidenceIndex(marketplace=marketplace, period=period)
        entities = extract.extract_concentration(reply, kind=kind, node_id_path=subject_id,
                                                 period=period, index=index)
        store.replace_concentration(marketplace, subject_id, period, kind, entities)
        store.record_evidence(index.all_rows())
        return JobResult(status="done", calls=int(reply.billable),
                         detail=f"{len(entities)} entities")
    return handler


def _rotating_slot(*, marketplace: str, period: str, subject_id: str,
                   bucket: str) -> JobResult:
    """One extra distribution per flagship per month, cycled through the set.

    Buying all five every month would double the structure budget for signals that
    move slowly; cycling makes the picture a quarter deep instead of a month wide.
    """
    try:
        offset = int(period) % len(_ROTATION)
    except ValueError:
        offset = 0
    tool, kind, family = _ROTATION[offset]
    handler = (_distribution_job if family == "distribution" else _concentration_job)(tool, kind)
    result = handler(marketplace=marketplace, period=period, subject_id=subject_id,
                     bucket=bucket)
    return JobResult(status=result.status, calls=result.calls,
                     detail=f"{kind}: {result.detail}")


def _product_pack(*, marketplace: str, period: str, subject_id: str,
                  bucket: str) -> JobResult:
    """Fifty ASINs of full metrics in one call — the best calls-to-facts ratio here.

    Also the node's evidence for who the incumbents are, and the trigger that
    enqueues the per-ASIN packs for a flagship.
    """
    reply = gateway.call(
        "product_research",
        _request(marketplace=marketplace, nodeIdPath=subject_id, nodeIdPathEqual="false",
                 month=period, size=PRODUCT_PAGE_SIZE,
                 order={"field": "total_amount", "desc": True}),
        bucket=bucket, purpose="product pack", marketplace=marketplace)
    if not _ok(reply):
        return JobResult(status="pending", calls=int(reply.billable), detail=reply.detail)

    index = EvidenceIndex(marketplace=marketplace, period=period)
    products, metrics = extract.extract_products(
        reply, node_id_path=subject_id, period=period, marketplace=marketplace, index=index)
    store.upsert_products(products)
    store.upsert_product_metrics(metrics)
    store.record_evidence(index.all_rows())

    followups = 0
    if subject_id in taxonomy.TIER1_PATHS:
        # Per-ASIN work cannot be planned in advance; the ASINs only exist now.
        for row in metrics[:FLAGSHIP_ASINS]:
            for kind, priority in (("flagship_reviews", 85), ("flagship_traffic", 75),
                                   ("flagship_keywords", 80), ("flagship_history", 65)):
                store.enqueue_job(marketplace=marketplace, job_kind=kind,
                                  subject_kind="asin", subject_id=row["asin"],
                                  period=period, priority=priority, est_calls=1)
                followups += 1
    return JobResult(status="done", calls=int(reply.billable),
                     detail=f"{len(products)} products", followups=followups)


def _product_newcomers(*, marketplace: str, period: str, subject_id: str,
                       bucket: str) -> JobResult:
    """Recently listed ASINs that already sell — the proof a newcomer can win here."""
    reply = gateway.call(
        "product_research",
        _request(marketplace=marketplace, nodeIdPath=subject_id, nodeIdPathEqual="false",
                 month=period, size=30, minRevenue=20000,
                 order={"field": "available_date", "desc": True}),
        bucket=bucket, purpose="new entrants", marketplace=marketplace)
    if not _ok(reply):
        return JobResult(status="pending", calls=int(reply.billable), detail=reply.detail)
    products, metrics = extract.extract_products(
        reply, node_id_path=subject_id, period=period, marketplace=marketplace)
    store.upsert_products(products)
    store.upsert_product_metrics(metrics)
    return JobResult(status="done", calls=int(reply.billable),
                     detail=f"{len(products)} new entrants")


def _keyword_aba(*, marketplace: str, period: str, subject_id: str,
                 bucket: str) -> JobResult:
    reply = gateway.call(
        "aba_research_monthly",
        _request(marketplace=marketplace, date=period, size=50, minSearches=2000,
                 order={"field": "searches", "desc": True}),
        bucket=bucket, purpose="ABA movers", marketplace=marketplace)
    if not _ok(reply):
        return JobResult(status="pending", calls=int(reply.billable), detail=reply.detail)
    index = EvidenceIndex(marketplace=marketplace, period=period)
    rows = extract.extract_keywords(reply, period=period, marketplace=marketplace,
                                    index=index)
    store.upsert_keyword_metrics(rows)
    store.record_evidence(index.all_rows())
    return JobResult(status="done", calls=int(reply.billable), detail=f"{len(rows)} keywords")


def _keyword_demand(*, marketplace: str, period: str, subject_id: str,
                    bucket: str) -> JobResult:
    """``keyword_research`` takes a keyword list, so one call covers a whole node."""
    label = taxonomy.short_label(taxonomy.label_for(subject_id, marketplace)).lower()
    seed = label.replace(" & ", " ").strip()
    reply = gateway.call(
        "keyword_research",
        _request(marketplace=marketplace, keywords=seed, month=period, size=50,
                 withYearlyGrowth=True),
        bucket=bucket, purpose="keyword demand", marketplace=marketplace)
    if not _ok(reply):
        return JobResult(status="pending", calls=int(reply.billable), detail=reply.detail)
    index = EvidenceIndex(marketplace=marketplace, period=period)
    rows = extract.extract_keywords(reply, period=period, node_id_path=subject_id,
                                    marketplace=marketplace, index=index)
    store.upsert_keyword_metrics(rows)
    store.record_evidence(index.all_rows())
    return JobResult(status="done", calls=int(reply.billable), detail=f"{len(rows)} keywords")


def _flagship_traffic(*, marketplace: str, period: str, subject_id: str,
                      bucket: str) -> JobResult:
    """Natural vs ad vs recommendation — whether entry costs reviews or ad spend."""
    reply = gateway.call(
        "traffic_source",
        _request(marketplace=marketplace, q=subject_id, month=period, size=10),
        bucket=bucket, purpose="traffic mix", marketplace=marketplace)
    if not _ok(reply):
        return JobResult(status="pending", calls=int(reply.billable), detail=reply.detail)
    index = EvidenceIndex(marketplace=marketplace, period=period)
    mix = extract.extract_traffic_mix(reply, asin=subject_id, period=period, index=index)
    if mix:
        store.upsert_product_metrics([{
            "marketplace": marketplace, "asin": subject_id, "period": period,
            "source_tool": "traffic_source",
            "natural_proportion": mix.get("natural_proportion"),
            "ad_proportion": mix.get("ad_proportion"),
            "recommendation_proportion": mix.get("recommendation_proportion"),
        }])
    store.record_evidence(index.all_rows())
    return JobResult(status="done", calls=int(reply.billable), detail="traffic mix")


def _flagship_keywords(*, marketplace: str, period: str, subject_id: str,
                       bucket: str) -> JobResult:
    reply = gateway.call(
        "traffic_keyword",
        _request(marketplace=marketplace, asin=subject_id, month=period, size=30,
                 trafficKeywordTypes=["primary", "precise"]),
        bucket=bucket, purpose="keyword edges", marketplace=marketplace)
    if not _ok(reply):
        return JobResult(status="pending", calls=int(reply.billable), detail=reply.detail)
    index = EvidenceIndex(marketplace=marketplace, period=period)
    edges = extract.extract_keyword_edges(reply, asin=subject_id, period=period,
                                          marketplace=marketplace, index=index)
    store.upsert_keyword_edges(edges)
    store.record_evidence(index.all_rows())
    return JobResult(status="done", calls=int(reply.billable), detail=f"{len(edges)} edges")


def _flagship_history(*, marketplace: str, period: str, subject_id: str,
                      bucket: str) -> JobResult:
    """One call carries 14 months, so this runs once per ASIN and then idles."""
    reply = gateway.call(
        "asin_prediction", {"marketplace": marketplace, "asin": subject_id},
        bucket=bucket, purpose="asin history", marketplace=marketplace)
    if not _ok(reply):
        return JobResult(status="pending", calls=int(reply.billable), detail=reply.detail)
    history = extract.extract_asin_history(reply, asin=subject_id, marketplace=marketplace)
    store.upsert_product_history(history)
    return JobResult(status="done", calls=int(reply.billable), detail=f"{len(history)} points")


def _flagship_reviews(*, marketplace: str, period: str, subject_id: str,
                      bucket: str) -> JobResult:
    """Negative reviews only: the pain points a product design can remove.

    The prose is not stored — ``render`` themes it and ``store.replace_review_themes``
    keeps the themes plus a few quotes.
    """
    reply = gateway.call(
        "review",
        {"marketplace": marketplace, "asin": subject_id, "starList": [1, 2, 3],
         "size": 50, "page": 1},
        bucket=bucket, purpose="pain points", marketplace=marketplace)
    if not _ok(reply):
        return JobResult(status="pending", calls=int(reply.billable), detail=reply.detail)
    reviews = extract.extract_reviews(reply, asin=subject_id, marketplace=marketplace)
    _REVIEW_CACHE[(marketplace, subject_id, period)] = reviews
    return JobResult(status="done", calls=int(reply.billable), detail=f"{len(reviews)} reviews")


# Review prose is deliberately not persisted (third-party text, no analytical value
# once themed). It lives in-process between collection and theming; a render that
# finds nothing here simply reports the pain-point section as a gap.
_REVIEW_CACHE: dict[tuple[str, str, str], list[dict]] = {}


def cached_reviews(marketplace: str, asin: str, period: str) -> list[dict]:
    return _REVIEW_CACHE.get((marketplace, asin, period), [])


def clear_review_cache() -> None:
    _REVIEW_CACHE.clear()


def _offamazon_trend(*, marketplace: str, period: str, subject_id: str,
                     bucket: str) -> JobResult:
    label = taxonomy.short_label(taxonomy.label_for(subject_id, marketplace)).lower()
    reply = gateway.call(
        "google_trend", _request(marketplace=marketplace, keyword=label),
        bucket=bucket, purpose="off-Amazon demand", marketplace=marketplace)
    if not _ok(reply):
        return JobResult(status="pending", calls=int(reply.billable), detail=reply.detail)
    series = extract.extract_google_trend(reply, keyword=label)
    store.upsert_keyword_metrics([
        {"marketplace": marketplace, "keyword": label, "period": point["period"],
         "node_id_path": subject_id, "google_trend_index": point["google_trend_index"],
         "source_tool": "google_trend"}
        for point in series
    ])
    return JobResult(status="done", calls=int(reply.billable), detail=f"{len(series)} months")


# -------------------------------------------------------------- job catalog ----

CATALOG: tuple[JobSpec, ...] = (
    JobSpec("department_roll", "department", 20, 1, "month", _department_roll,
            scope="department"),
    JobSpec("category_structure", "node", 30, 2, "month", _category_structure),
    JobSpec("category_demand", "node", 30, 1, "month", _category_demand),
    JobSpec("category_price_bands", "node", 35, 1, "month",
            _distribution_job("market_price_distribution", "price")),
    JobSpec("category_newcomers", "node", 35, 1, "month",
            _distribution_job("market_listing_date_distribution", "listing_date")),
    JobSpec("category_brands", "node", 40, 1, "month",
            _concentration_job("market_brand_concentration", "brand")),
    JobSpec("product_pack", "node", 25, 1, "week", _product_pack),
    JobSpec("product_newcomers", "node", 45, 1, "month", _product_newcomers),
    JobSpec("keyword_aba", "department", 50, 1, "month", _keyword_aba, scope="department"),
    JobSpec("keyword_demand", "node", 55, 1, "month", _keyword_demand),
    JobSpec("category_rotating", "node", 60, 1, "month", _rotating_slot, tier=1),
    JobSpec("offamazon_trend", "node", 70, 1, "month", _offamazon_trend, tier=1),
    # Per-ASIN, enqueued by product_pack once the ASINs are known.
    JobSpec("flagship_history", "asin", 65, 1, "month", _flagship_history),
    JobSpec("flagship_traffic", "asin", 75, 1, "month", _flagship_traffic),
    JobSpec("flagship_keywords", "asin", 80, 1, "month", _flagship_keywords),
    JobSpec("flagship_reviews", "asin", 85, 1, "month", _flagship_reviews),
)

BY_KIND: dict[str, JobSpec] = {spec.kind: spec for spec in CATALOG}

# The steps a node's month is considered to consist of, for ``completeness``.
NODE_PACK = ("category_structure", "category_demand", "category_price_bands",
             "category_newcomers", "category_brands", "product_pack",
             "product_newcomers", "keyword_demand")


def plan_period(marketplace: str, period: str) -> int:
    """Enqueue everything a month needs. Idempotent — re-planning adds nothing."""
    taxonomy.ensure_nodes(marketplace)
    before = store.queue_depth(marketplace)
    for spec in CATALOG:
        if spec.subject_kind == "asin":
            continue        # enqueued by product_pack, once the ASINs exist
        if spec.scope == "department":
            store.enqueue_job(marketplace=marketplace, job_kind=spec.kind,
                              subject_kind="department", subject_id=taxonomy.FURNITURE_ROOT,
                              period=period, priority=spec.priority,
                              est_calls=spec.est_calls)
            continue
        for node in taxonomy.leaf_nodes(marketplace):
            if spec.tier is not None and node["tier"] != spec.tier:
                continue
            store.enqueue_job(marketplace=marketplace, job_kind=spec.kind,
                              subject_kind="node", subject_id=node["node_id_path"],
                              period=period, priority=spec.priority,
                              est_calls=spec.est_calls)
    return store.queue_depth(marketplace) - before


def run_job(job: dict, *, marketplace: str = "US", bucket: str = gateway.BUCKET_SWEEP) -> JobResult:
    """Execute one job and record its outcome. Never raises for a vendor refusal."""
    spec = BY_KIND.get(job["job_kind"])
    if spec is None:
        store.finish_job(job["id"], status="blocked", error="unknown job kind")
        return JobResult(status="blocked", detail="unknown job kind")

    try:
        result = spec.handler(marketplace=marketplace, period=job["period"],
                              subject_id=job["subject_id"], bucket=bucket)
    except BudgetExhausted as exc:
        # Leave the job exactly as it was: tomorrow resumes here.
        return JobResult(status="budget", detail=str(exc))
    except McpUnavailable:
        # The transport is down, which is a property of the run and not of this
        # job. Swallowing it here would charge every remaining job an attempt and
        # a backoff for an outage none of them caused.
        raise
    except Exception as exc:  # noqa: BLE001 — one bad job must not sink the sweep
        logger.warning("market job %s failed: %s", job["job_kind"], exc)
        result = JobResult(status="pending", detail=str(exc)[:300])

    if result.status == "done":
        store.finish_job(job["id"], status="done")
        return result

    attempts = int(job.get("attempts") or 0) + 1
    if attempts >= MAX_ATTEMPTS:
        # Three refusals is a declared gap, not a retry loop. The dashboard names it.
        store.finish_job(job["id"], status="blocked", error=result.detail,
                         bump_attempts=True)
        return JobResult(status="blocked", calls=result.calls, detail=result.detail)
    delay = BACKOFF_SECONDS[min(attempts - 1, len(BACKOFF_SECONDS) - 1)]
    store.finish_job(job["id"], status="pending", error=result.detail,
                     next_due_at=gateway.sweep_now().timestamp() + delay,
                     bump_attempts=True)
    return JobResult(status="pending", calls=result.calls, detail=result.detail)


def node_completeness(marketplace: str, node_id_path: str, period: str) -> tuple[float, list[str]]:
    """Which of a node's monthly pack landed, from the job queue's own record."""
    done: list[str] = []
    with_conn = store.db.connect()
    try:
        rows = with_conn.execute(
            "SELECT job_kind, status FROM market_jobs WHERE marketplace = ? "
            "AND subject_kind = 'node' AND subject_id = ? AND period = ?",
            (marketplace, node_id_path, period),
        ).fetchall()
    finally:
        with_conn.close()
    for row in rows:
        if row["status"] == "done" and row["job_kind"] in NODE_PACK:
            done.append(row["job_kind"])
    return extract.completeness(done, NODE_PACK)
