"""The daily sweep: claim the day, drain the queue to the cap, record what happened.

Transactional **per job**, not per sweep. Each job writes its own rows and is marked
done before the next starts, so hitting the cap mid-queue is an ordinary stopping
point: the remaining jobs stay ``pending`` with their due time untouched and
tomorrow resumes exactly there. Nothing is rolled back and nothing is re-paid.

``est_calls`` is checked before starting a job so a two-call job never begins with
one call of budget left — a half-ingested job is the one failure mode that would
leave the warehouse inconsistent.
"""
from __future__ import annotations

import logging

from marketing_agent.tools import sellersprite
from marketing_agent.tools.mcp_client import McpUnavailable

from . import gateway, jobs, store, taxonomy
from .gateway import BudgetExhausted

logger = logging.getLogger(__name__)


def is_due(marketplace: str = "US") -> bool:
    """True when today's sweep has not been claimed yet."""
    if not gateway.enabled() or not sellersprite.is_configured():
        return False
    latest = store.latest_run(marketplace)
    return not latest or latest["run_date"] != gateway.run_date()


def target_period(now=None) -> str:
    """Which month a sweep should collect.

    Early in a month the current month has almost nothing in it, so the first days
    keep filling the previous month — otherwise the board would go blank on the 1st
    and slowly refill, which reads as a market collapse rather than a calendar.
    """
    moment = now or gateway.sweep_now()
    return gateway.previous_period(moment) if moment.day <= 5 else gateway.current_period(moment)


def run_daily_sweep(marketplace: str = "US", *, budget: int | None = None) -> dict:
    """Drain the due queue against today's cap. Returns a summary of the run."""
    if not gateway.enabled():
        return {"status": "disabled", "calls_used": 0, "jobs_done": 0}
    if not sellersprite.is_configured():
        return {"status": "unconfigured", "calls_used": 0, "jobs_done": 0}

    limit = gateway.DAILY_LIMITS.get(gateway.BUCKET_SWEEP, 0) if budget is None else budget
    if limit <= 0:
        # A misconfigured env must not be able to produce an unbounded sweep.
        return {"status": "no_budget", "calls_used": 0, "jobs_done": 0}

    day = gateway.run_date()
    period = target_period()
    run = store.claim_run(marketplace, day, period, limit)
    if run is None:
        # Another worker owns today. The unique index is the lock.
        return {"status": "claimed_elsewhere", "calls_used": 0, "jobs_done": 0}

    taxonomy.ensure_nodes(marketplace)
    planned = jobs.plan_period(marketplace, period)

    done = failed = 0
    status = "complete"
    detail = ""
    try:
        while True:
            spent = store.calls_used(marketplace, day, gateway.BUCKET_SWEEP)
            remaining = limit - spent
            if remaining <= 0:
                status = "budget_exhausted"
                break
            batch = store.due_jobs(marketplace, limit=50)
            if not batch:
                break
            progressed = False
            for job in batch:
                spent = store.calls_used(marketplace, day, gateway.BUCKET_SWEEP)
                if spent + int(job["est_calls"]) > limit:
                    # Never start a job that cannot finish inside the budget.
                    status = "budget_exhausted"
                    progressed = False
                    break
                result = jobs.run_job(job, marketplace=marketplace)
                progressed = True
                if result.status == "done":
                    done += 1
                elif result.status == "budget":
                    status = "budget_exhausted"
                    progressed = False
                    break
                else:
                    failed += 1
            if not progressed:
                break
    except McpUnavailable as exc:
        # Transport down: nothing was metered, jobs keep their due times, tomorrow
        # picks up unchanged. This is the one case that is not a budget event.
        status = "aborted"
        detail = str(exc)[:300]
    except BudgetExhausted as exc:
        status = "budget_exhausted"
        detail = str(exc)[:300]

    calls_used = store.calls_used(marketplace, day, gateway.BUCKET_SWEEP)
    depth = store.queue_depth(marketplace)
    store.finish_run(run["id"], status=status, calls_used=calls_used, jobs_done=done,
                     jobs_failed=failed, queue_depth_after=depth, detail=detail)
    logger.info("market sweep %s: %s, %d calls, %d jobs, %d queued",
                day, status, calls_used, done, depth)
    return {
        "status": status, "run_id": run["id"], "run_date": day, "period": period,
        "budget": limit, "calls_used": calls_used, "jobs_done": done,
        "jobs_failed": failed, "jobs_planned": planned, "queue_depth": depth,
        "detail": detail,
    }
