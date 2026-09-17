"""The one path from this package to a metered vendor call.

Everything the warehouse ingests goes through :func:`call`. Concentrating it here is
what makes four otherwise-scattered guarantees checkable in one place:

* **A daily budget that is actually enforced.** Wallets (``sweep`` / ``deepdive`` /
  ``chat``) are counted independently in ``market_call_log``, so a burst of
  on-demand research can never eat the scheduled snapshot's allowance.
* **A call is billed once.** Identical arguments inside a short window are served
  from the process cache and logged ``billable=0``.
* **``returnFields`` by default.** See ``fields.py`` — on the ingest path it is a 4x
  payload cut, and on the agent path it is the difference between valid and
  truncated JSON.
* **pytest can never spend credits.** ``conftest.py`` already clears the key; this
  module refuses regardless, because the real hole is a test that sets the key back
  and forgets to fake the transport.

What this module does *not* do is decide what to call or what to keep. Job planning
lives in ``jobs.py`` and parsing in ``extract.py``; a gateway that also knew the
collection plan would be impossible to test without one.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from zoneinfo import ZoneInfo

from marketing_agent.tools import sellersprite
from marketing_agent.tools.mcp_client import McpToolError, McpUnavailable

from . import fields as field_sets
from . import store

logger = logging.getLogger(__name__)

_FALSEY = {"0", "false", "no", "off", ""}

MARKETPLACE = "US"
# The vendor's own clock. The collector this replaced used the server's local
# month, so a China- or UTC-hosted box asked for a month the US marketplace had not
# entered yet and got empty replies for the first hours of every month.
SWEEP_TZ = os.environ.get("MARKETING_AGENT_MARKET_TZ", "America/Los_Angeles")

# Wallets. Separate ledgers, separate caps, checked before every call.
BUCKET_SWEEP = "sweep"
BUCKET_DEEPDIVE = "deepdive"
BUCKET_CHAT = "chat"
BUCKET_MANUAL = "manual"

# The sweep cap governs how fast a month fills, not how much a month costs —
# total spend is set by the job catalog (~355 calls a month, ~12 a day steady
# state; the keyword miner is ~24 of those, two pages per tracked node, and is
# the one line item tuned by an env var rather than by the catalog). At 45 the
# month-opening burst took five days to drain, and the board was thin and
# unrankable for most of that. At 150 it drains in about two.
DAILY_LIMITS = {
    BUCKET_SWEEP: int(os.environ.get("MARKETING_AGENT_MARKET_DAILY_CALLS", "150")),
    BUCKET_DEEPDIVE: int(os.environ.get("MARKETING_AGENT_MARKET_DEEPDIVE_DAILY", "120")),
    BUCKET_CHAT: int(os.environ.get("MARKETING_AGENT_MARKET_CHAT_DAILY", "60")),
    BUCKET_MANUAL: int(os.environ.get("MARKETING_AGENT_MARKET_MANUAL_DAILY", "40")),
}

PROCESS_CACHE_TTL = float(os.environ.get("MARKETING_AGENT_MARKET_CACHE_TTL", "900"))
# One rename at the vendor would otherwise turn every call into a silent empty and
# the warehouse would record a month of gaps instead of an error.
MAX_FIELD_DRIFT_RETRIES = 3

_LOCK = threading.Lock()
_CACHE: dict[tuple[str, str], tuple[float, str]] = {}
_DRIFT_RETRIES: dict[str, int] = {}


class BudgetExhausted(RuntimeError):
    """The wallet for this call is spent. Not an error — a stopping condition."""


@dataclass
class VendorReply:
    """One vendor call's outcome. Never raises for a vendor-side refusal."""

    tool: str
    arguments: dict
    payload: str = ""
    status: str = "ok"          # ok | empty | rejected | error | cached | field_drift
    call_id: str = ""
    billable: bool = False
    elapsed_ms: int = 0
    detail: str = ""
    rows: int = 0
    data: object = field(default=None, repr=False)

    @property
    def ok(self) -> bool:
        return self.status in ("ok", "cached") and bool(self.payload.strip())


def sweep_now(tz: str = SWEEP_TZ) -> datetime:
    try:
        return datetime.now(ZoneInfo(tz))
    except Exception:  # noqa: BLE001 — unknown tz string
        return datetime.now(ZoneInfo("UTC"))


def run_date(now: datetime | None = None) -> str:
    return (now or sweep_now()).strftime("%Y-%m-%d")


def current_period(now: datetime | None = None) -> str:
    """The marketplace-local month, ``yyyyMM``."""
    return (now or sweep_now()).strftime("%Y%m")


def previous_period(now: datetime | None = None) -> str:
    """Last month — what a fresh sweep should collect for the first days of a month,
    because the current month has barely any data in it yet."""
    moment = now or sweep_now()
    year, month = moment.year, moment.month - 1
    if month == 0:
        year, month = year - 1, 12
    return f"{year}{month:02d}"


def step_period(period: str, months: int) -> str:
    """Shift a ``yyyyMM`` key by whole months; ``""`` when it cannot be parsed.

    Returning empty rather than raising: the callers use this to look for an
    optional comparison month, and a malformed key should cost them the
    comparison, not the whole render.
    """
    try:
        year, month = int(period[:4]), int(period[4:6])
    except (TypeError, ValueError, IndexError):
        return ""
    if not 1 <= month <= 12:
        return ""
    index = year * 12 + (month - 1) + months
    return f"{index // 12}{index % 12 + 1:02d}"


def enabled() -> bool:
    return os.environ.get("MARKETING_AGENT_MARKET_SWEEP", "1").strip().lower() not in _FALSEY


def _live_vendor_opt_in() -> bool:
    return os.environ.get("MARKETING_AGENT_TEST_LIVE_VENDOR", "").strip().lower() not in _FALSEY


def _under_pytest() -> bool:
    return bool(os.environ.get("PYTEST_CURRENT_TEST"))


def args_hash(tool: str, arguments: dict) -> str:
    try:
        canonical = json.dumps(arguments, ensure_ascii=False, sort_keys=True, default=str)
    except (TypeError, ValueError):
        canonical = repr(sorted(arguments.items()))
    return hashlib.sha1(f"{tool}|{canonical}".encode("utf-8")).hexdigest()[:16]


def remaining(bucket: str, *, marketplace: str = MARKETPLACE, day: str | None = None) -> int:
    limit = DAILY_LIMITS.get(bucket, 0)
    if limit <= 0:
        return 0
    return max(0, limit - store.calls_used(marketplace, day or run_date(), bucket))


def budget_status(marketplace: str = MARKETPLACE, day: str | None = None) -> dict:
    """What the analyst view and ``/api/market/budget`` report."""
    today = day or run_date()
    return {
        "run_date": today,
        "marketplace": marketplace,
        "wallets": {
            bucket: {
                "limit": limit,
                "used": store.calls_used(marketplace, today, bucket),
                "remaining": remaining(bucket, marketplace=marketplace, day=today),
            }
            for bucket, limit in DAILY_LIMITS.items()
        },
        "total_used": store.calls_used(marketplace, today),
    }


def clear_cache() -> None:
    with _LOCK:
        _CACHE.clear()
        _DRIFT_RETRIES.clear()


def _cached(key: tuple[str, str]) -> str | None:
    with _LOCK:
        entry = _CACHE.get(key)
        if entry is None or time.time() - entry[0] > PROCESS_CACHE_TTL:
            return None
        return entry[1]


def _remember(key: tuple[str, str], payload: str) -> None:
    with _LOCK:
        _CACHE[key] = (time.time(), payload)


def _row_count(payload: str) -> tuple[int, object]:
    """Rows in a reply, for the call log. Cheap enough to do on every call and it is
    the signal that tells a field rename apart from a genuinely empty market."""
    try:
        data = json.loads(payload)
    except (ValueError, TypeError):
        return 0, None
    body = data.get("data") if isinstance(data, dict) else data
    if isinstance(body, dict):
        for key in ("items", "records", "list", "rows"):
            if isinstance(body.get(key), list):
                return len(body[key]), data
        return 1, data
    if isinstance(body, list):
        return len(body), data
    return 0 if body in (None, "") else 1, data


def call(
    tool: str,
    arguments: dict,
    *,
    bucket: str = BUCKET_SWEEP,
    purpose: str = "",
    marketplace: str = MARKETPLACE,
    prune_fields: bool = True,
    allow_drift_retry: bool = True,
) -> VendorReply:
    """Make one vendor call, or explain why it did not happen.

    Raises only for conditions the caller must stop on: :class:`BudgetExhausted`
    when the wallet is spent, and :class:`McpUnavailable` when the transport is
    down (nothing was metered, so the whole run should stand down and retry later).
    A vendor-side refusal is an answer, not an exception: it comes back as
    ``status='rejected'`` with ``billable=True``, because the call was charged.
    """
    day = run_date()

    if _under_pytest() and not _live_vendor_opt_in():
        # conftest.py clears the key, but a test that sets it back and forgets to
        # fake the transport would reach the network. This is the backstop.
        raise McpUnavailable(
            "Refusing a metered vendor call from inside pytest. Set "
            "MARKETING_AGENT_TEST_LIVE_VENDOR=1 to opt in deliberately."
        )
    if not sellersprite.is_configured():
        raise McpUnavailable(sellersprite.unavailable_reason())

    prepared = field_sets.apply(tool, arguments) if prune_fields else arguments
    digest = args_hash(tool, prepared)
    key = (tool, digest)

    hit = _cached(key)
    if hit is not None:
        rows, data = _row_count(hit)
        call_id = store.log_call(
            marketplace=marketplace, tool=tool, arguments=prepared, arguments_hash=digest,
            bucket=bucket, purpose=purpose, run_date=day, status="cached", billable=False,
            payload_bytes=len(hit), rows_extracted=rows,
        )
        return VendorReply(tool=tool, arguments=prepared, payload=hit, status="cached",
                           call_id=call_id, billable=False, rows=rows, data=data)

    if remaining(bucket, marketplace=marketplace, day=day) <= 0:
        raise BudgetExhausted(
            f"The {bucket} wallet is spent for {day} "
            f"({DAILY_LIMITS.get(bucket, 0)} calls). Remaining work stays queued."
        )

    started = time.monotonic()
    try:
        payload = sellersprite.call_tool(tool, prepared)
    except McpToolError as exc:
        elapsed = int((time.monotonic() - started) * 1000)
        call_id = store.log_call(
            marketplace=marketplace, tool=tool, arguments=prepared, arguments_hash=digest,
            bucket=bucket, purpose=purpose, run_date=day, status="rejected",
            billable=True, elapsed_ms=elapsed, detail=str(exc),
        )
        return VendorReply(tool=tool, arguments=prepared, status="rejected", call_id=call_id,
                           billable=True, elapsed_ms=elapsed, detail=str(exc)[:300])
    except McpUnavailable as exc:
        # Transport down: nothing was metered, so this is not a budget event.
        store.log_call(
            marketplace=marketplace, tool=tool, arguments=prepared, arguments_hash=digest,
            bucket=bucket, purpose=purpose, run_date=day, status="unavailable",
            billable=False, detail=str(exc),
        )
        raise
    except Exception as exc:  # noqa: BLE001 — an unknown client-side failure
        elapsed = int((time.monotonic() - started) * 1000)
        logger.warning("market: %s failed: %s", tool, exc)
        call_id = store.log_call(
            marketplace=marketplace, tool=tool, arguments=prepared, arguments_hash=digest,
            bucket=bucket, purpose=purpose, run_date=day, status="error", billable=True,
            elapsed_ms=elapsed, detail=str(exc),
        )
        return VendorReply(tool=tool, arguments=prepared, status="error", call_id=call_id,
                           billable=True, elapsed_ms=elapsed, detail=str(exc)[:300])

    elapsed = int((time.monotonic() - started) * 1000)
    rows, data = _row_count(payload)

    if rows == 0 and allow_drift_retry and field_sets.has_fields(prepared):
        # An empty reply to a pruned call is ambiguous: an empty market, or a field
        # this repo asked for by a name the vendor no longer uses. Retrying bare
        # costs one call and turns a silent month of gaps into a logged rename.
        with _LOCK:
            used = _DRIFT_RETRIES.get(f"{day}|{tool}", 0)
        if used < MAX_FIELD_DRIFT_RETRIES:
            with _LOCK:
                _DRIFT_RETRIES[f"{day}|{tool}"] = used + 1
            store.log_call(
                marketplace=marketplace, tool=tool, arguments=prepared,
                arguments_hash=digest, bucket=bucket, purpose=purpose, run_date=day,
                status="field_drift", billable=True, elapsed_ms=elapsed,
                payload_bytes=len(payload),
                detail=f"empty with returnFields; retrying unpruned (retry {used + 1})",
            )
            return call(tool, field_sets.strip(prepared), bucket=bucket, purpose=purpose,
                        marketplace=marketplace, prune_fields=False, allow_drift_retry=False)

    status = "ok" if rows else "empty"
    call_id = store.log_call(
        marketplace=marketplace, tool=tool, arguments=prepared, arguments_hash=digest,
        bucket=bucket, purpose=purpose, run_date=day, status=status, billable=True,
        payload_bytes=len(payload), rows_extracted=rows, elapsed_ms=elapsed,
    )
    if rows:
        _remember(key, payload)
    return VendorReply(tool=tool, arguments=prepared, payload=payload, status=status,
                       call_id=call_id, billable=True, elapsed_ms=elapsed, rows=rows,
                       data=data)
