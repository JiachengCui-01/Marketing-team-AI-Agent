"""On-demand category deep dive: the expensive half, spent only when asked.

The scheduled sweep keeps monthly snapshots for every tracked node — cheap,
category-level, one call per fact table. Keywords, per-ASIN traffic, reviews and
history are one call *per entity*, so they run here, against their own wallet, when
a user actually opens a category.

A deep dive is keyed by ``(node, period)`` and shared: the second person to ask for
the same category in the same month reads the stored result and pays nothing.
"""
from __future__ import annotations

import logging
import os

from marketing_agent.tools.mcp_client import McpUnavailable

from . import gateway, jobs, store, taxonomy
from .gateway import BudgetExhausted

logger = logging.getLogger(__name__)

MAX_CALLS_PER_RUN = int(os.environ.get("MARKETING_AGENT_MARKET_DEEPDIVE_CALLS", "40"))
# How many ASINs get the per-entity packs. Four is two more than the sweep's
# flagship pair, which is what makes a deep dive worth its cost.
DEEP_ASINS = 4

# Ordered: cheap structure first so a dive that runs out of budget still leaves a
# readable category, expensive per-ASIN work last.
NODE_STEPS: tuple[str, ...] = (
    "category_structure",
    "category_demand",
    "category_price_bands",
    "category_newcomers",
    "category_brands",
    "product_pack",
    "product_newcomers",
    "keyword_demand",
    "category_rotating",
)
ASIN_STEPS: tuple[str, ...] = (
    "flagship_reviews",
    "flagship_keywords",
    "flagship_traffic",
    "flagship_history",
)


def plan(node_id_path: str, period: str) -> list[dict]:
    """The step list, recorded on the run so a partial dive can say what it skipped."""
    steps = [{"step": kind, "subject_kind": "node", "subject_id": node_id_path,
              "status": "pending"} for kind in NODE_STEPS]
    # ASIN steps are appended once product_pack has told us which ASINs exist.
    return steps


def _run_step(step: dict, *, marketplace: str, period: str) -> int:
    """Execute one step through the job machinery, on the deep-dive wallet."""
    store.enqueue_job(marketplace=marketplace, job_kind=step["step"],
                      subject_kind=step["subject_kind"], subject_id=step["subject_id"],
                      period=period, priority=10,
                      est_calls=jobs.BY_KIND[step["step"]].est_calls)
    queued = next((j for j in store.due_jobs(marketplace, limit=500)
                   if j["job_kind"] == step["step"]
                   and j["subject_id"] == step["subject_id"]
                   and j["period"] == period), None)
    if queued is None:
        # Already done this month by the sweep: nothing to buy.
        step["status"] = "cached"
        return 0
    result = jobs.run_job(queued, marketplace=marketplace,
                          bucket=gateway.BUCKET_DEEPDIVE)
    step["status"] = "done" if result.status == "done" else result.status
    step["detail"] = result.detail
    return result.calls


def run_deepdive(
    *, node_id_path: str, marketplace: str = "US", period: str | None = None,
    user_id: str | None = None, force: bool = False, max_calls: int | None = None,
) -> dict:
    """Collect everything a category page needs. Returns the deep-dive record.

    Raises :class:`McpUnavailable` when the vendor is down — the caller turns that
    into a 502, and nothing was charged.
    """
    period = period or gateway.previous_period()
    budget = MAX_CALLS_PER_RUN if max_calls is None else max_calls
    node = store.get_node(marketplace, node_id_path)
    if node is None and node_id_path not in taxonomy.TRACKED_PATHS:
        # An unknown node is a caller error, not a data gap: analysing whatever the
        # id happens to point at is exactly what node resolution exists to prevent.
        raise ValueError(f"unknown category node: {node_id_path}")
    taxonomy.ensure_nodes(marketplace)

    existing = store.get_deepdive(marketplace, node_id_path, period)
    if existing and not force:
        return existing
    if existing and force:
        store.clear_deepdive(marketplace, node_id_path, period)

    steps = plan(node_id_path, period)
    record = store.start_deepdive(marketplace=marketplace, node_id_path=node_id_path,
                                  period=period, requested_by=user_id,
                                  calls_budget=budget, plan=steps)
    if record is None:
        # Someone else claimed it between the read and the write.
        return store.get_deepdive(marketplace, node_id_path, period) or {}

    used = 0
    status = "complete"
    detail = ""
    try:
        for step in steps:
            if used >= budget:
                status = "partial"
                step["status"] = "skipped"
                continue
            used += _run_step(step, marketplace=marketplace, period=period)
            if step["step"] == "product_pack":
                steps.extend(_asin_steps(marketplace, node_id_path, period))
    except BudgetExhausted as exc:
        status = "partial"
        detail = str(exc)[:300]
        for step in steps:
            step.setdefault("status", "pending")
            if step["status"] == "pending":
                step["status"] = "skipped"
    except McpUnavailable as exc:
        store.finish_deepdive(marketplace, node_id_path, period, status="failed",
                              calls_used=used, plan=steps, detail=str(exc)[:300])
        raise
    except Exception as exc:  # noqa: BLE001 — a broken step must not lose the rest
        logger.warning("deep dive %s failed: %s", node_id_path, exc)
        status = "partial"
        detail = str(exc)[:300]

    if any(s["status"] in ("skipped", "pending") for s in steps):
        status = "partial"
    store.finish_deepdive(marketplace, node_id_path, period, status=status,
                          calls_used=used, plan=steps, detail=detail)
    return store.get_deepdive(marketplace, node_id_path, period) or {}


def _asin_steps(marketplace: str, node_id_path: str, period: str) -> list[dict]:
    """Per-ASIN steps for the node's top sellers, once they are known."""
    products = store.top_products(marketplace, node_id_path, period, limit=DEEP_ASINS)
    return [{"step": kind, "subject_kind": "asin", "subject_id": product["asin"],
             "status": "pending"}
            for product in products for kind in ASIN_STEPS]


def skipped_steps(record: dict) -> list[str]:
    """What a partial dive did not do, for the report's gap list."""
    return [f"{s['step']}({s['subject_id'][-8:]})" for s in record.get("plan", [])
            if s.get("status") in ("skipped", "pending", "blocked")]
