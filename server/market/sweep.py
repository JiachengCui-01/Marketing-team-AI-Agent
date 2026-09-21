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
    """Which month a sweep should collect: the last **closed** one, always.

    ``market_research`` is a monthly aggregate — revenue, units, brand
    concentration, the return rate, the newcomer ratios — and the vendor only
    publishes it once a month has ended. Asked for a month still in progress it
    returns no rows at all, which is not the same as returning small ones.

    This used to switch to the current month from the 6th, on the theory that by
    then it had "firmed up". It had not: the board then held only the fields that
    come from ``market_research_statistics`` (a live listing snapshot, which
    answers any time), so revenue read as $0, the return rate was unknown for
    every category, and five of the seven scoring factors scored zero — an
    evidence coverage of 0.27 on every row.

    A board dated last month is accurate. A board dated this month is empty.
    """
    return gateway.previous_period(now or gateway.sweep_now())


def _drain(marketplace: str, *, day: str, bucket: str,
           limit: int) -> tuple[int, int, str, str]:
    """Run due jobs against one wallet until it empties or the queue does.

    Returns ``(done, failed, status, detail)``. Lifted out of the daily sweep so
    a manual collection can reuse it: the loop never cared which wallet it was
    spending, only that it stops before a job it cannot finish.
    """
    done = failed = 0
    status = "complete"
    detail = ""
    try:
        while True:
            spent = store.calls_used(marketplace, day, bucket)
            if limit - spent <= 0:
                status = "budget_exhausted"
                break
            batch = store.due_jobs(marketplace, limit=50)
            if not batch:
                break
            progressed = False
            for job in batch:
                spent = store.calls_used(marketplace, day, bucket)
                if spent + int(job["est_calls"]) > limit:
                    # Never start a job that cannot finish inside the budget.
                    status = "budget_exhausted"
                    progressed = False
                    break
                result = jobs.run_job(job, marketplace=marketplace, bucket=bucket)
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
    return done, failed, status, detail


def collect_now(marketplace: str = "US") -> dict:
    """What the 「采集最新数据」 button runs. Always collects if there is anything to.

    The button used to call :func:`run_daily_sweep`, which claims the calendar day
    through a unique index before it does anything. The scheduler claims that day
    within a minute of midnight, so from then on every click returned
    ``claimed_elsewhere`` having spent nothing — and the route dropped the status
    on the floor and re-rendered the same data, so the button looked like it
    worked and changed nothing. Every day. That is the whole bug.

    So: claim the day if it is still free — a first run of the day should get the
    sweep's own budget, which is what a cold start needs — and otherwise top the
    queue up from ``BUCKET_MANUAL``, a wallet that was defined for exactly this
    and had no caller. Either way the queue is what gets drained, and the caller
    is told which happened and what it cost.
    """
    if not gateway.enabled():
        return {"status": "disabled", "calls_used": 0, "jobs_done": 0, "queue_depth": 0}
    if not sellersprite.is_configured():
        return {"status": "unconfigured", "calls_used": 0, "jobs_done": 0, "queue_depth": 0}

    if is_due(marketplace):
        run = run_daily_sweep(marketplace)
        if run.get("status") != "claimed_elsewhere":
            return {**run, "mode": "sweep"}
        # Lost the race with the scheduler between the check and the claim.

    day = gateway.run_date()
    period = target_period()
    limit = gateway.DAILY_LIMITS.get(gateway.BUCKET_MANUAL, 0)
    if limit <= 0:
        return {"status": "no_budget", "mode": "manual", "calls_used": 0,
                "jobs_done": 0, "queue_depth": store.queue_depth(marketplace)}

    taxonomy.ensure_nodes(marketplace)
    # Idempotent: re-planning an already-planned month adds nothing. Worth doing
    # anyway, because the one case where the button is pressed in anger is the
    # one where the scheduler's run failed before it got here.
    jobs.plan_period(marketplace, period)
    jobs.plan_pulse(marketplace)
    store.park_future_jobs(marketplace, period, exempt_kinds=jobs.PULSE_KINDS)

    before = store.queue_depth(marketplace)
    if not store.due_jobs(marketplace, limit=1):
        # Not a failure: nothing is *due*. `queue_depth` counts every pending
        # job including the ones backing off after a vendor refusal, so the two
        # numbers are reported apart — "nothing to collect" beside a queue of
        # twelve reads as a contradiction otherwise.
        return {"status": "nothing_due", "mode": "manual", "calls_used": 0,
                "jobs_done": 0, "queue_depth": before, "due_now": 0,
                "period": period}

    done, failed, status, detail = _drain(marketplace, day=day,
                                          bucket=gateway.BUCKET_MANUAL, limit=limit)
    calls_used = store.calls_used(marketplace, day, gateway.BUCKET_MANUAL)
    depth = store.queue_depth(marketplace)
    logger.info("manual collect %s: %s, %d calls, %d jobs, %d queued",
                day, status, calls_used, done, depth)
    return {"status": status, "mode": "manual", "run_date": day, "period": period,
            "budget": limit, "calls_used": calls_used, "jobs_done": done,
            "jobs_failed": failed, "queue_depth": depth,
            "due_now": len(store.due_jobs(marketplace, limit=500)), "detail": detail}


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
    # One cheap live reading per node per week, against the month still in
    # progress. It is the only thing the board can say about today.
    planned += jobs.plan_pulse(marketplace)
    # Anything else queued against a month newer than the target cannot be served
    # yet. Retrying it three times per node is most of a day's budget spent
    # proving the calendar. Parked now, woken by plan_period once that month
    # closes.
    parked = store.park_future_jobs(marketplace, period,
                                    exempt_kinds=jobs.PULSE_KINDS)

    done, failed, status, detail = _drain(marketplace, day=day, bucket=gateway.BUCKET_SWEEP,
                                          limit=limit)

    calls_used = store.calls_used(marketplace, day, gateway.BUCKET_SWEEP)
    depth = store.queue_depth(marketplace)
    store.finish_run(run["id"], status=status, calls_used=calls_used, jobs_done=done,
                     jobs_failed=failed, queue_depth_after=depth, detail=detail)
    logger.info("market sweep %s: %s, %d calls, %d jobs, %d queued",
                day, status, calls_used, done, depth)
    return {
        "status": status, "run_id": run["id"], "run_date": day, "period": period,
        "budget": limit, "calls_used": calls_used, "jobs_done": done,
        "jobs_failed": failed, "jobs_planned": planned, "jobs_parked": parked,
        "queue_depth": depth,
        "detail": detail,
    }
