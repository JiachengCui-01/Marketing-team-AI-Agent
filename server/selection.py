"""The legacy product-selection surface, now a thin shell over the market warehouse.

This module used to do its own metered sweep: four SellerSprite calls per watched
category, up to sixteen per user per day, then a model call to reshape the raw
payloads into a dashboard. ``server/market/`` replaced that with a **global**
warehouse — the US furniture market is the same market for every user, so paying
for it per user was paying N times for one answer — and with an ingest/render
split that makes a model outage cost nothing.

What survives here is the part that is genuinely per-user: the schedule, the
cancellation grace period, the category picker, and the legacy ``/api/selection/*``
response shape that a cached web bundle still asks for. ``generate_report`` now
**projects the stored market board** into that shape. It makes zero vendor calls,
and it reuses a board already rendered for the same period and language, so N
users cost one render rather than N.

Nothing here fetches. If the warehouse is empty the answer is a loud error, not a
guess — a selection recommendation that is not grounded in marketplace data is a
guess dressed as analysis.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, time as dtime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from marketing_agent import provenance
from marketing_agent.domain import PRODUCT_CATEGORIES

from . import db, llm
from .market import render as market_render
from .market import store as market_store

logger = logging.getLogger(__name__)

MAX_CATEGORIES = 4
DEFAULT_MARKETPLACE = "US"
# Marketplaces the vendor enumerates; the UI offers these and the API validates them.
MARKETPLACES = (
    "US", "JP", "UK", "DE", "FR", "IT", "ES", "CA", "IN", "MX", "BR", "AU", "AE",
)

# "All categories" means the brand's own product line, not the whole of Amazon —
# a recommendation outside what this company can design and freight is noise.
ALL_CATEGORY_KEYWORDS = tuple(PRODUCT_CATEGORIES)

# How many board rows the legacy dashboard carries. The old schema was built for a
# handful of hand-picked categories, not for a twelve-node sweep.
LEGACY_ROWS = 8


class SelectionGenerationError(RuntimeError):
    """Raised when the analysis could not be produced from vendor data."""


# Browse-node resolution moved to ``server/market/taxonomy.py`` when the market
# warehouse took over collection: the market package needs it for deep dives on
# categories outside the tracked catalog, and one scorer beats two. Re-exported
# here so existing callers and tests keep the old import path.
from .market.taxonomy import (  # noqa: E402,F401  (re-exports, placed with the code they replaced)
    _HOME_FURNITURE_PREFIX,
    _STOPWORDS,
    _category_tokens,
    pick_node,
)

__all__ = [
    "MARKETPLACES", "DEFAULT_MARKETPLACE", "MAX_CATEGORIES", "ALL_CATEGORY_KEYWORDS",
    "SelectionGenerationError", "generate_report", "is_due", "is_cancelled",
    "is_cancel_expired", "cancellation_revert_ts", "resolve_categories",
    "purge_user_data", "pick_node",
]


# ------------------------------------------------------------------ schedule ----

def is_cancelled(config_row: dict | None) -> bool:
    return bool(config_row) and not config_row.get("enabled") and config_row.get("cancelled_at") is not None


def cancellation_revert_ts(config_row: dict) -> float:
    """Match news cancellation: retain results until tomorrow's scheduled run time."""
    tz = _config_tz(config_row)
    cancelled_local = datetime.fromtimestamp(float(config_row["cancelled_at"]), tz=tz)
    try:
        hh, mm = (int(x) for x in str(config_row["refresh_time"]).split(":"))
    except (ValueError, KeyError):
        hh, mm = 9, 0
    next_day = (cancelled_local + timedelta(days=1)).date()
    return datetime.combine(next_day, dtime(hour=hh, minute=mm), tzinfo=tz).timestamp()


def is_cancel_expired(config_row: dict | None, now_ts: float) -> bool:
    return bool(is_cancelled(config_row) and now_ts >= cancellation_revert_ts(config_row))


def _config_tz(config_row: dict) -> ZoneInfo:
    try:
        return ZoneInfo(config_row.get("timezone") or "UTC")
    except Exception:  # noqa: BLE001 — unknown tz string
        return ZoneInfo("UTC")


def is_due(config_row: dict, now: datetime) -> bool:
    """True if this config's daily run is due at ``now`` (in the config's timezone)."""
    try:
        hh, mm = (int(x) for x in str(config_row["refresh_time"]).split(":"))
    except (ValueError, KeyError):
        return False
    scheduled = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if now < scheduled:
        return False
    last = config_row.get("last_run_at")
    if last is None:
        return True
    return datetime.fromtimestamp(last, tz=now.tzinfo) < scheduled


def resolve_categories(config_row: dict) -> list[str]:
    """The category keywords this run should analyze."""
    if str(config_row.get("scope") or "all") == "all":
        return list(ALL_CATEGORY_KEYWORDS[:MAX_CATEGORIES])
    picked = [str(c).strip() for c in (config_row.get("categories") or []) if str(c).strip()]
    return picked[:MAX_CATEGORIES] or list(ALL_CATEGORY_KEYWORDS[:MAX_CATEGORIES])


def purge_user_data(user_id: str) -> None:
    """Everything this user owns, across both the legacy and the market tables.

    The warehouse itself is global and deliberately survives: it is nobody's
    personal data and re-collecting it would cost real vendor credits. What goes
    is the user's own rendered artifacts — their dashboards and their PRDs —
    which ``db.delete_selection_data`` alone never touched.
    """
    db.delete_selection_data(user_id)
    market_store.delete_user_market_data(user_id)


# ------------------------------------------------------------------ projection ----

def _competition(share_pct: float | None) -> str:
    """Top-5 brand revenue share, as the legacy schema's three-valued field."""
    if share_pct is None:
        return "medium"
    if share_pct >= 55.0:
        return "high"
    if share_pct <= 25.0:
        return "low"
    return "medium"


def _money(value: Any) -> str:
    from .market.panels import money

    return money(value)


def _pct_text(value: float | None) -> str:
    return "—" if value is None else f"{value:.1f}%"


_MOVE_LABELS = {
    "enter": ("立项", "start"),
    "validate": ("先验证", "validate first"),
    "watch": ("观望", "watch"),
}


def _selection_markdown(dashboard: dict, zh: bool) -> str:
    """The selection picks as the markdown the legacy summary opens with.

    A projection of the same structured block the board renders as cards — not a
    second writing of it. The export has no card layout to lean on, so each pick
    becomes one bolded line and its supporting fields become the clause after
    it, in the order a selection meeting asks for them.
    """
    selection = dashboard.get("selection") or {}
    picks = selection.get("picks") or []
    if not picks:
        return ""
    labels = {row["node_key"]: row["label"] for row in (dashboard.get("board") or [])}
    lines = ["## 本期选品建议" if zh else "## Selection"]
    if selection.get("call"):
        lines.append(str(selection["call"]))
    for index, pick in enumerate(picks, 1):
        shelf = labels.get(pick.get("node_key"), pick.get("node_key") or "")
        move = _MOVE_LABELS.get(str(pick.get("move")), ("", ""))[0 if zh else 1]
        head = f"{index}. **{shelf} · {pick.get('spec', '')}**"
        if move:
            head += f"（{move}）" if zh else f" ({move})"
        lines.append(head)
        for key, label in (("why_now", "为什么是现在" if zh else "Why now"),
                           ("price_band", "目标价格带" if zh else "Price band"),
                           ("envelope", "物理包络" if zh else "Envelope"),
                           ("fix", "要解决" if zh else "Fix"),
                           ("risk", "风险" if zh else "Risk")):
            if pick.get(key):
                lines.append(f"   - {label}：{pick[key]}" if zh
                             else f"   - {label}: {pick[key]}")
    avoid = selection.get("avoid") or []
    if avoid:
        lines.append("**建议规避**" if zh else "**Do not start**")
        for row in avoid:
            lines.append(f"- {row.get('label', '')} — {row.get('why', '')}")
    return "\n".join(lines)


def project_dashboard(dashboard: dict, language: str) -> tuple[dict, str]:
    """The market board in the legacy dashboard shape, plus its summary.

    A projection rather than a second renderer: every number here already exists
    on the board, computed once, so the two surfaces can never disagree about
    what the market did.
    """
    zh = language != "en"
    board = list(dashboard.get("board") or [])[:LEGACY_ROWS]
    verdicts = dashboard.get("verdicts") or {}

    recommendations = []
    for row in board:
        verdict = verdicts.get(row["node_key"]) or {}
        recommendations.append({
            "title": row["label"],
            "category": row.get("node_label_path") or row["label"],
            "price": _money(row.get("median_price")),
            "monthly_revenue": _money(row.get("revenue_est")),
            "rating": "",
            "reviews": "",
            "competition": _competition(row.get("top5_brand_share_pct")),
            "reason": verdict.get("rationale") or (
                f"机会分 {row['category_score']}/100" if zh
                else f"Opportunity score {row['category_score']}/100"),
            "score": row.get("category_score"),
            "score_breakdown": row.get("score_breakdown"),
        })

    market = [{
        "category": row["label"],
        "avg_price": _money(row.get("median_price")),
        "avg_revenue": _money(row.get("revenue_est")),
        "avg_rating": "",
        "brand_concentration": _pct_text(row.get("top5_brand_share_pct")),
        "verdict": (verdicts.get(row["node_key"]) or {}).get("verdict")
        or (verdicts.get(row["node_key"]) or {}).get("rationale") or "",
    } for row in board]

    trends = []
    department = dashboard.get("trend") or []
    if len(department) >= 2:
        first, last = department[0]["value"], department[-1]["value"]
        trends.append({
            "category": "家具部门" if zh else "Furniture department",
            "label": "月销售额" if zh else "Monthly revenue",
            "unit": "USD",
            "change_pct": round((last - first) / first * 100.0, 1) if first else 0.0,
            "points": department,
        })

    # The picks lead the summary, ahead of the thesis. This string is what the
    # report list shows and what the export carries, and a reader who only sees
    # its first paragraph should be reading the conclusion rather than the
    # market description the conclusion was drawn from.
    summary = str(dashboard.get("thesis") or "")
    picks = _selection_markdown(dashboard, zh)
    if picks:
        summary = f"{picks}\n\n{summary}" if summary else picks
    monitor_summary = str(dashboard.get("monitor_summary") or "")
    if monitor_summary:
        heading = "\n\n## 风险与机会\n\n" if zh else "\n\n## Risks and opportunities\n\n"
        summary = f"{summary}{heading}{monitor_summary}"

    legacy = {
        "kpis": list(dashboard.get("headline", {}).get("kpis") or []),
        "recommendations": recommendations,
        "market": market,
        "trends": trends,
        "notes": list(dashboard.get("gaps") or []),
    }
    return legacy, summary


# ------------------------------------------------------------------ generation ----

def generate_report(config_row: dict, client=None) -> dict:
    """Persist one legacy-shaped report, projected from the market warehouse.

    Zero vendor calls by construction — collection is the sweep's job and it is
    global. A board already rendered for this period and language is reused, so
    the Nth user of the day costs nothing at all rather than another model call.
    """
    marketplace = str(config_row.get("marketplace") or DEFAULT_MARKETPLACE).upper()
    language = str(config_row.get("language") or "zh")
    if language not in {"zh", "en"}:
        language = "zh"

    record = market_store.latest_dashboard(marketplace=marketplace, scope="overview",
                                           language=language)
    if record is None:
        # Nothing rendered yet for this language. Rendering is free of vendor
        # credits, so do it here rather than making the user wait for tomorrow.
        client = client or llm.get_client()
        if client is None:
            raise SelectionGenerationError("DEEPSEEK_API_KEY 未配置，无法生成选品分析。")
        try:
            record = market_render.render_overview(marketplace=marketplace,
                                                   language=language, client=client)
        except market_render.RenderError as exc:
            raise SelectionGenerationError(str(exc)) from exc

    if record.get("status") != "ok":
        raise SelectionGenerationError(
            record.get("summary")
            or ("市场仓库本期还没有可用数据，请先在「全盘发现」运行一次采集。" if language == "zh"
                else "The market warehouse has no usable data for this period yet.")
        )

    dashboard, summary = project_dashboard(record["dashboard"], language)
    ledger = provenance.SourceLedger()
    tools = list(record.get("vendor_tools") or [])
    ledger.record(provenance.SELLERSPRITE,
                  f"{len(tools)} 个接口" if language == "zh" else f"{len(tools)} endpoints")
    summary = provenance.append_section(summary, ledger, language)

    stored = db.add_selection_report(
        user_id=config_row["user_id"],
        marketplace=marketplace,
        scope=str(config_row.get("scope") or "all"),
        categories=resolve_categories(config_row),
        dashboard=dashboard,
        summary=summary,
        vendor_tools=tools,
        generated_at=time.time(),
    )
    db.set_selection_config_last_run(config_row["user_id"], stored["generated_at"])
    return stored
