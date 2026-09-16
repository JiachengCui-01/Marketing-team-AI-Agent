"""All market-warehouse SQL.

Kept out of ``server/db.py`` so that file does not grow another 700 lines; it owns
the schema (``MARKET_SCHEMA``) and this module owns the access.

Two conventions run through everything here:

**Upsert, never insert.** Every fact table has a unique key ending in ``period``,
and the vendor restates a month as it firms up. Each upsert writes
``COALESCE(excluded.col, col)`` so a partial re-fetch fills gaps instead of blanking
columns an earlier pass already landed.

**The warehouse is global, not per-user.** The US Amazon furniture market is the
same market for every user of this workspace; keying facts by user would multiply a
30-60 call/day vendor budget by the user count. Only ``market_dashboards`` (when
``scope='category'``) and ``market_prds`` carry a ``user_id``.
"""
from __future__ import annotations

import json
import sqlite3
import time
import uuid
from typing import Any, Iterable, Mapping, Sequence

from server import db

RETAINED_SNAPSHOTS = 24          # user decision: two years of monthly history
CALL_PAYLOAD_TTL_DAYS = 7        # raw payloads live only long enough to re-parse
RUN_LOG_TTL_DAYS = 90

# (table, period column). Ordered parents-last so nothing is orphaned mid-prune.
_PERIOD_TABLES: tuple[tuple[str, str], ...] = (
    ("market_distributions", "period"),
    ("market_concentration", "period"),
    ("market_product_metrics", "period"),
    ("market_product_history", "period"),
    ("market_keyword_asin_edges", "period"),
    ("market_keyword_metrics", "period"),
    ("market_review_themes", "period"),
    ("market_scores", "period"),
    ("market_node_snapshots", "period"),
)


def _now() -> float:
    return time.time()


def _rows(cursor: sqlite3.Cursor) -> list[dict]:
    return [dict(row) for row in cursor.fetchall()]


def _json_load(value: Any, fallback: Any) -> Any:
    try:
        parsed = json.loads(value or "")
    except (ValueError, TypeError):
        return fallback
    return parsed if isinstance(parsed, type(fallback)) else fallback


def _dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _upsert(
    conn: sqlite3.Connection, table: str, key: Sequence[str], row: dict,
    *, insert_only: Sequence[str] = (), update_expr: dict[str, str] | None = None,
) -> None:
    """INSERT … ON CONFLICT(key) DO UPDATE with COALESCE on every non-key column.

    COALESCE rather than plain assignment: a job that only refreshed part of a
    month must not blank the columns a different job already filled.

    ``insert_only`` columns are left alone on conflict. COALESCE would not protect
    them — it prefers the incoming value, which is exactly wrong for a column like
    ``first_seen_at`` whose whole job is to remember the first sighting.
    """
    cols = list(row)
    overrides = update_expr or {}
    placeholders = ", ".join("?" for _ in cols)
    updates = ", ".join(
        f"{c} = {overrides.get(c, f'COALESCE(excluded.{c}, {table}.{c})')}"
        for c in cols if c not in key and c not in insert_only
    )
    conn.execute(
        f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({placeholders}) "
        f"ON CONFLICT({', '.join(key)}) DO UPDATE SET {updates}",
        [row[c] for c in cols],
    )


# ---------------------------------------------------------------- taxonomy ----

def upsert_nodes(nodes: Iterable[dict]) -> int:
    """Persist resolved browse nodes. Node ids are stable for years, so this runs
    once at bootstrap and never again — it is what frees the four ``product_node``
    calls the old sweep paid for on every single run."""
    db._ensure()
    now = _now()
    count = 0
    with db.connect() as conn:
        for node in nodes:
            path = str(node.get("node_id_path") or "").strip()
            if not path:
                continue
            label_path = str(node.get("node_label_path") or "")
            parts = [p for p in label_path.split(":") if p]
            _upsert(conn, "market_nodes", ("marketplace", "node_id_path"), {
                "marketplace": node.get("marketplace", "US"),
                "node_id_path": path,
                "node_label_path": label_path,
                "label": node.get("label") or (parts[-1] if parts else path),
                "parent_path": node.get("parent_path") or ":".join(path.split(":")[:-1]) or None,
                "depth": node.get("depth", max(0, len(path.split(":")) - 1)),
                "brand_category": node.get("brand_category"),
                "tracked": 1 if node.get("tracked") else 0,
                "tier": int(node.get("tier") or 2),
                "products": node.get("products"),
                "resolved_at": now,
                "updated_at": now,
            })
            count += 1
    return count


def get_node(marketplace: str, node_id_path: str) -> dict | None:
    db._ensure()
    with db.connect() as conn:
        row = conn.execute(
            "SELECT * FROM market_nodes WHERE marketplace = ? AND node_id_path = ?",
            (marketplace, node_id_path),
        ).fetchone()
    return dict(row) if row else None


def cap_tracked_nodes(marketplace: str, limit: int, *,
                      keep: Iterable[str] = ()) -> int:
    """Untrack the smallest categories once the tracked set passes ``limit``.

    An engineering limit, not an editorial one. Each tracked node costs roughly
    two dozen vendor calls a month, so an unbounded discovery walk can enrol
    faster than the daily budget can collect — and a month that never finishes
    collecting is worth less than a smaller month that does. The nodes dropped
    are the ones with the fewest listings, and the checked-in catalog is never
    dropped whatever its size.

    Returns how many were untracked.
    """
    protected = set(keep)
    db._ensure()
    with db.connect() as conn:
        rows = _rows(conn.execute(
            "SELECT node_id_path, products FROM market_nodes "
            "WHERE marketplace = ? AND tracked = 1", (marketplace,)))
        if len(rows) <= limit:
            return 0
        ranked = sorted(rows, key=lambda r: (r["node_id_path"] in protected,
                                             float(r["products"] or 0.0)),
                        reverse=True)
        drop = [r["node_id_path"] for r in ranked[limit:]
                if r["node_id_path"] not in protected]
        for path in drop:
            conn.execute("UPDATE market_nodes SET tracked = 0 "
                         "WHERE marketplace = ? AND node_id_path = ?",
                         (marketplace, path))
    return len(drop)


def list_nodes(marketplace: str = "US", *, tracked_only: bool = True) -> list[dict]:
    db._ensure()
    sql = "SELECT * FROM market_nodes WHERE marketplace = ?"
    params: list[Any] = [marketplace]
    if tracked_only:
        sql += " AND tracked = 1"
    sql += " ORDER BY tier ASC, node_label_path ASC"
    with db.connect() as conn:
        return _rows(conn.execute(sql, params))


# ------------------------------------------------------------- node facts ----

# Two kinds of fact share this table. ``month`` is the vendor's closed-month
# aggregate — revenue, concentration, returns — published only after a month
# ends. ``pulse`` is a point-in-time reading of the live listing snapshot, taken
# while the month is still open: real, but a run-rate rather than a total.
MONTH, PULSE = "month", "pulse"


def upsert_node_snapshot(
    marketplace: str,
    node_id_path: str,
    period: str,
    metrics: dict,
    *,
    completeness: float | None = None,
    missing: Sequence[str] | None = None,
    grain: str = MONTH,
    observed_at: float | None = None,
) -> None:
    """Write (or fill in) one category row for a period and grain.

    ``metrics`` keys must be real column names; unknown keys are dropped rather
    than raising, because an extractor that learns a new vendor field should not
    take down a whole sweep before the column exists.
    """
    db._ensure()
    with db.connect() as conn:
        known = db._table_columns(conn, "market_node_snapshots")
        row: dict[str, Any] = {
            k: v for k, v in metrics.items()
            if k in known and k not in ("id", "marketplace", "node_id_path", "period")
        }
        row.update({
            "id": uuid.uuid4().hex,
            "marketplace": marketplace,
            "node_id_path": node_id_path,
            "period": period,
            "grain": grain,
            "ingested_at": _now(),
            "updated_at": _now(),
        })
        if grain == PULSE:
            # A pulse is only meaningful with the moment it was taken; the month
            # it falls in is not a period the vendor has closed.
            row["observed_at"] = observed_at or _now()
        if completeness is not None:
            row["completeness"] = float(completeness)
        if missing is not None:
            row["missing_json"] = _dumps(list(missing))
        _upsert(conn, "market_node_snapshots",
                ("marketplace", "node_id_path", "period", "grain"), row)


def get_node_snapshot(marketplace: str, node_id_path: str, period: str,
                      *, grain: str = MONTH) -> dict | None:
    db._ensure()
    with db.connect() as conn:
        row = conn.execute(
            "SELECT * FROM market_node_snapshots "
            "WHERE marketplace = ? AND node_id_path = ? AND period = ? AND grain = ?",
            (marketplace, node_id_path, period, grain),
        ).fetchone()
    if not row:
        return None
    out = dict(row)
    out["missing"] = _json_load(out.pop("missing_json", "[]"), [])
    return out


def list_node_snapshots(marketplace: str, period: str,
                        *, grain: str = MONTH) -> list[dict]:
    """Every tracked node's row for one period and grain."""
    db._ensure()
    with db.connect() as conn:
        rows = _rows(conn.execute(
            "SELECT s.*, n.node_label_path, n.label, n.tier, n.brand_category "
            "FROM market_node_snapshots s "
            "JOIN market_nodes n ON n.marketplace = s.marketplace "
            "                   AND n.node_id_path = s.node_id_path "
            "WHERE s.marketplace = ? AND s.period = ? AND s.grain = ? "
            "ORDER BY s.total_revenue DESC",
            (marketplace, period, grain),
        ))
    for row in rows:
        row["missing"] = _json_load(row.pop("missing_json", "[]"), [])
    return rows


def latest_pulse(marketplace: str) -> list[dict]:
    """The most recent live reading for every tracked node.

    One row per node, newest first by observation time — a pulse taken a week
    apart for two nodes is still the newest each has, and dropping the older one
    would silently shrink the panel.
    """
    db._ensure()
    with db.connect() as conn:
        rows = _rows(conn.execute(
            "SELECT s.*, n.node_label_path, n.label, n.tier, n.brand_category "
            "FROM market_node_snapshots s "
            "JOIN market_nodes n ON n.marketplace = s.marketplace "
            "                   AND n.node_id_path = s.node_id_path "
            "JOIN (SELECT node_id_path, MAX(observed_at) AS seen "
            "      FROM market_node_snapshots WHERE marketplace = ? AND grain = ? "
            "      GROUP BY node_id_path) latest "
            "  ON latest.node_id_path = s.node_id_path AND latest.seen = s.observed_at "
            "WHERE s.marketplace = ? AND s.grain = ? "
            "ORDER BY s.observed_at DESC, s.node_id_path ASC",
            (marketplace, PULSE, marketplace, PULSE),
        ))
    for row in rows:
        row["missing"] = _json_load(row.pop("missing_json", "[]"), [])
    return rows


# The column that decides whether a month is worth rendering. It is the one the
# board, the treemap, the trend line and three scoring factors all read, and it
# only ever arrives from ``market_research`` — the vendor's monthly aggregate.
_USABLE_COLUMN = "total_revenue"


def latest_period(marketplace: str, node_id_path: str | None = None,
                  *, usable_only: bool = True) -> str | None:
    """The newest month worth rendering — not merely the newest month that exists.

    ``MAX(period)`` was the obvious rule and it was wrong at every month
    boundary. The vendor publishes monthly aggregates only once a month closes,
    but the live listing snapshot answers immediately, so a partially-collected
    current month leaves rows holding an average price and nothing else. Ranked
    by ``MAX(period)`` that stub outranks a complete previous month, and the
    board renders the emptier of the two: $0 revenue, no return rates, and five
    of seven scoring factors at zero.

    So prefer the newest month that carries the aggregate. If none does — a fresh
    install, or a vendor outage across every month — fall back to the newest
    month with any rows at all, because rendering something honestly marked
    incomplete beats rendering nothing.
    """
    db._ensure()
    where = "marketplace = ?"
    params: list[Any] = [marketplace]
    if node_id_path:
        where += " AND node_id_path = ?"
        params.append(node_id_path)

    with db.connect() as conn:
        if usable_only:
            row = conn.execute(
                f"SELECT MAX(period) AS period FROM market_node_snapshots "
                f"WHERE {where} AND grain = '{MONTH}' "
                f"AND {_USABLE_COLUMN} IS NOT NULL", params,
            ).fetchone()
            if row and row["period"]:
                return str(row["period"])
        row = conn.execute(
            f"SELECT MAX(period) AS period FROM market_node_snapshots "
            f"WHERE {where} AND grain = '{MONTH}'",
            params,
        ).fetchone()
    return row["period"] if row and row["period"] else None


def snapshot_history(marketplace: str, node_id_path: str, *, limit: int = 24) -> list[dict]:
    """Oldest-first monthly series for one node — the trend line and the growth factor."""
    db._ensure()
    with db.connect() as conn:
        rows = _rows(conn.execute(
            "SELECT period, total_revenue, total_units, avg_price, avg_rating, "
            "       return_ratio, glance_views, new_ratio_l12 "
            "FROM market_node_snapshots "
            "WHERE marketplace = ? AND node_id_path = ? AND grain = 'month' "
            "ORDER BY period DESC LIMIT ?",
            (marketplace, node_id_path, limit),
        ))
    return list(reversed(rows))


def replace_distribution(
    marketplace: str, node_id_path: str, period: str, kind: str, buckets: Iterable[dict]
) -> int:
    """Replace one distribution wholesale.

    Unlike the metric tables this is a replace, not a merge: a bucket that vanished
    from the vendor's reply has genuinely vanished from the market, and leaving a
    stale bucket behind would make the shares stop summing to 100%.
    """
    db._ensure()
    now = _now()
    count = 0
    with db.connect() as conn:
        conn.execute(
            "DELETE FROM market_distributions WHERE marketplace = ? AND node_id_path = ? "
            "AND period = ? AND kind = ?",
            (marketplace, node_id_path, period, kind),
        )
        for order, bucket in enumerate(buckets):
            key = str(bucket.get("bucket_key") or "").strip()
            if not key:
                continue
            conn.execute(
                "INSERT INTO market_distributions (id, marketplace, node_id_path, period, "
                "kind, bucket_key, bucket_order, products, products_ratio, revenue, "
                "revenue_ratio, units, units_ratio, evidence_id, ingested_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (uuid.uuid4().hex, marketplace, node_id_path, period, kind, key, order,
                 bucket.get("products"), bucket.get("products_ratio"), bucket.get("revenue"),
                 bucket.get("revenue_ratio"), bucket.get("units"), bucket.get("units_ratio"),
                 bucket.get("evidence_id"), now),
            )
            count += 1
    return count


def get_distribution(marketplace: str, node_id_path: str, period: str, kind: str) -> list[dict]:
    db._ensure()
    with db.connect() as conn:
        return _rows(conn.execute(
            "SELECT * FROM market_distributions WHERE marketplace = ? AND node_id_path = ? "
            "AND period = ? AND kind = ? ORDER BY bucket_order ASC",
            (marketplace, node_id_path, period, kind),
        ))


def all_distributions(marketplace: str, node_id_path: str, period: str) -> dict[str, list[dict]]:
    """Every distribution kind held for one node-month, keyed by kind.

    The rotating collector buys a different distribution each month, so which
    kinds exist is data, not a constant — the caller renders what came back
    rather than asking for a fixed five and drawing four empty charts.
    """
    db._ensure()
    with db.connect() as conn:
        rows = _rows(conn.execute(
            "SELECT * FROM market_distributions WHERE marketplace = ? AND node_id_path = ? "
            "AND period = ? ORDER BY kind ASC, bucket_order ASC",
            (marketplace, node_id_path, period),
        ))
    out: dict[str, list[dict]] = {}
    for row in rows:
        out.setdefault(row["kind"], []).append(row)
    return out


def replace_concentration(
    marketplace: str, node_id_path: str, period: str, kind: str, entities: Iterable[dict]
) -> int:
    """Replace one concentration table (brand / seller / seller_type / product)."""
    db._ensure()
    now = _now()
    count = 0
    with db.connect() as conn:
        conn.execute(
            "DELETE FROM market_concentration WHERE marketplace = ? AND node_id_path = ? "
            "AND period = ? AND kind = ?",
            (marketplace, node_id_path, period, kind),
        )
        for rank, item in enumerate(entities, start=1):
            entity = str(item.get("entity") or "").strip()
            if not entity:
                continue
            conn.execute(
                "INSERT INTO market_concentration (id, marketplace, node_id_path, period, "
                "kind, entity, rank, products, revenue, revenue_ratio, units, units_ratio, "
                "new_products, new_revenue_ratio, rating, ratings, evidence_id, ingested_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (uuid.uuid4().hex, marketplace, node_id_path, period, kind, entity,
                 item.get("rank", rank), item.get("products"), item.get("revenue"),
                 item.get("revenue_ratio"), item.get("units"), item.get("units_ratio"),
                 item.get("new_products"), item.get("new_revenue_ratio"),
                 item.get("rating"), item.get("ratings"), item.get("evidence_id"), now),
            )
            count += 1
    return count


def get_concentration(
    marketplace: str, node_id_path: str, period: str, kind: str, *, limit: int = 20
) -> list[dict]:
    db._ensure()
    with db.connect() as conn:
        return _rows(conn.execute(
            "SELECT * FROM market_concentration WHERE marketplace = ? AND node_id_path = ? "
            "AND period = ? AND kind = ? ORDER BY rank ASC LIMIT ?",
            (marketplace, node_id_path, period, kind, limit),
        ))


def all_concentration(
    marketplace: str, node_id_path: str, period: str, *, limit: int = 15
) -> dict[str, list[dict]]:
    """Every concentration kind held for one node-month, keyed by kind."""
    db._ensure()
    with db.connect() as conn:
        rows = _rows(conn.execute(
            "SELECT * FROM market_concentration WHERE marketplace = ? AND node_id_path = ? "
            "AND period = ? ORDER BY kind ASC, rank ASC",
            (marketplace, node_id_path, period),
        ))
    out: dict[str, list[dict]] = {}
    for row in rows:
        bucket = out.setdefault(row["kind"], [])
        if len(bucket) < limit:
            bucket.append(row)
    return out


# ---------------------------------------------------------------- products ----

def upsert_products(rows: Iterable[dict]) -> int:
    db._ensure()
    now = _now()
    count = 0
    with db.connect() as conn:
        known = db._table_columns(conn, "market_products")
        for item in rows:
            asin = str(item.get("asin") or "").strip()
            if not asin:
                continue
            row = {k: v for k, v in item.items() if k in known}
            row.update({
                "marketplace": item.get("marketplace", "US"),
                "asin": asin,
                "last_seen_at": now,
            })
            row.setdefault("first_seen_at", now)
            _upsert(conn, "market_products", ("marketplace", "asin"), row,
                    insert_only=("first_seen_at",))
            count += 1
    return count


def upsert_product_metrics(rows: Iterable[dict]) -> int:
    db._ensure()
    now = _now()
    count = 0
    with db.connect() as conn:
        known = db._table_columns(conn, "market_product_metrics")
        for item in rows:
            asin = str(item.get("asin") or "").strip()
            period = str(item.get("period") or "").strip()
            if not asin or not period:
                continue
            row = {k: v for k, v in item.items() if k in known and k != "id"}
            row.update({
                "id": uuid.uuid4().hex,
                "marketplace": item.get("marketplace", "US"),
                "asin": asin,
                "period": period,
                "ingested_at": now,
            })
            # An ASIN can come back under both a parent node and its child. The
            # deeper path is the better attribution, so the more specific node wins
            # regardless of which job happened to run last.
            _upsert(conn, "market_product_metrics", ("marketplace", "asin", "period"), row,
                    update_expr={"node_id_path":
                                 "CASE WHEN LENGTH(excluded.node_id_path) >= "
                                 "LENGTH(market_product_metrics.node_id_path) "
                                 "THEN excluded.node_id_path "
                                 "ELSE market_product_metrics.node_id_path END"})
            count += 1
    return count


def top_products(
    marketplace: str, node_id_path: str, period: str, *, limit: int = 20,
    order_by: str = "revenue",
) -> list[dict]:
    """The competitive set for one node-month, joined to the product dimension."""
    column = {"revenue": "m.revenue", "units": "m.units", "bsr": "m.bsr",
              "rating": "m.rating", "ratings": "m.ratings"}.get(order_by, "m.revenue")
    direction = "ASC" if order_by == "bsr" else "DESC"
    db._ensure()
    with db.connect() as conn:
        return _rows(conn.execute(
            f"SELECT m.*, p.title, p.brand, p.seller_name, p.seller_nation, p.fulfillment, "
            f"       p.available_date, p.variations, p.dimension, p.weight "
            f"FROM market_product_metrics m "
            f"LEFT JOIN market_products p ON p.marketplace = m.marketplace AND p.asin = m.asin "
            f"WHERE m.marketplace = ? AND m.period = ? AND m.node_id_path = ? "
            f"ORDER BY {column} IS NULL, {column} {direction} LIMIT ?",
            (marketplace, period, node_id_path, limit),
        ))


def all_products(marketplace: str, period: str, *, limit: int = 800) -> list[dict]:
    """Every ASIN row stored for a month, across all nodes, joined to its title.

    The element matrix reads titles department-wide: a style is not a property of
    one node, and "fluted" split across six categories is six numbers too small
    to mean anything separately.
    """
    db._ensure()
    with db.connect() as conn:
        return _rows(conn.execute(
            "SELECT m.asin, m.node_id_path, m.price, m.revenue, m.units, m.rating, "
            "       m.ratings, p.title, p.brand, p.variations, p.weight "
            "FROM market_product_metrics m "
            "LEFT JOIN market_products p ON p.marketplace = m.marketplace "
            "                           AND p.asin = m.asin "
            "WHERE m.marketplace = ? AND m.period = ? "
            "ORDER BY m.revenue IS NULL, m.revenue DESC LIMIT ?",
            (marketplace, period, limit),
        ))


def product_totals(marketplace: str, period: str) -> dict[str, dict]:
    """Summed ASIN revenue and units per node, from the rows actually collected.

    The vendor publishes no whole-category total — its ``totalRevenue`` covers
    the ~100 head listings it analyses — so the only figure the board can state
    honestly is the one it can point at row by row. Returned with the count so
    the panel can say what it covered rather than implying it covered
    everything.
    """
    db._ensure()
    with db.connect() as conn:
        rows = _rows(conn.execute(
            "SELECT node_id_path, COUNT(*) AS asins, "
            "       SUM(revenue) AS revenue, SUM(units) AS units "
            "FROM market_product_metrics "
            "WHERE marketplace = ? AND period = ? AND node_id_path IS NOT NULL "
            "GROUP BY node_id_path",
            (marketplace, period),
        ))
    return {row["node_id_path"]: row for row in rows}


def upsert_product_history(rows: Iterable[dict]) -> int:
    db._ensure()
    now = _now()
    count = 0
    with db.connect() as conn:
        for item in rows:
            asin = str(item.get("asin") or "").strip()
            period = str(item.get("period") or "").strip()
            metric = str(item.get("metric") or "").strip()
            if not (asin and period and metric):
                continue
            _upsert(conn, "market_product_history",
                    ("marketplace", "asin", "period", "grain", "metric"), {
                        "id": uuid.uuid4().hex,
                        "marketplace": item.get("marketplace", "US"),
                        "asin": asin,
                        "period": period,
                        "grain": item.get("grain", "month"),
                        "metric": metric,
                        "value": item.get("value"),
                        "observed": 1 if item.get("observed", True) else 0,
                        "source_tool": item.get("source_tool", ""),
                        "ingested_at": now,
                    })
            count += 1
    return count


def product_history(
    marketplace: str, asin: str, metric: str, *, grain: str = "month", limit: int = 24
) -> list[dict]:
    db._ensure()
    with db.connect() as conn:
        rows = _rows(conn.execute(
            "SELECT period, value, observed FROM market_product_history "
            "WHERE marketplace = ? AND asin = ? AND metric = ? AND grain = ? "
            "ORDER BY period DESC LIMIT ?",
            (marketplace, asin, metric, grain, limit),
        ))
    return list(reversed(rows))


# ---------------------------------------------------------------- keywords ----

def upsert_keyword_metrics(rows: Iterable[dict]) -> int:
    db._ensure()
    now = _now()
    count = 0
    with db.connect() as conn:
        known = db._table_columns(conn, "market_keyword_metrics")
        for item in rows:
            keyword = str(item.get("keyword") or "").strip()
            period = str(item.get("period") or "").strip()
            if not keyword or not period:
                continue
            row = {k: v for k, v in item.items() if k in known and k != "id"}
            row.update({
                "id": uuid.uuid4().hex,
                "marketplace": item.get("marketplace", "US"),
                "keyword": keyword,
                "period": period,
                "grain": item.get("grain", "month"),
                "ingested_at": now,
            })
            _upsert(conn, "market_keyword_metrics",
                    ("marketplace", "keyword", "period", "grain"), row)
            count += 1
    return count


def top_keywords(
    marketplace: str, node_id_path: str | None, period: str, *, limit: int = 30,
) -> list[dict]:
    db._ensure()
    sql = ("SELECT * FROM market_keyword_metrics WHERE marketplace = ? AND period = ? "
           "AND grain = 'month'")
    params: list[Any] = [marketplace, period]
    if node_id_path:
        sql += " AND (node_id_path = ? OR node_id_path IS NULL)"
        params.append(node_id_path)
    sql += " ORDER BY searches IS NULL, searches DESC LIMIT ?"
    params.append(limit)
    with db.connect() as conn:
        return _rows(conn.execute(sql, params))


def keyword_series(
    marketplace: str, node_id_path: str, column: str = "google_trend_index",
    *, limit: int = 24,
) -> list[dict]:
    """One keyword column as a monthly series for a node, oldest first.

    Off-Amazon demand is collected against the node's own label, so the series
    is addressed by node rather than by keyword: the caller charting it does not
    need to know which seed phrase the collector happened to use.
    """
    if column not in {"google_trend_index", "searches", "supply_demand_ratio"}:
        raise ValueError(f"unsupported keyword series column: {column}")
    db._ensure()
    with db.connect() as conn:
        rows = _rows(conn.execute(
            f"SELECT period, keyword, {column} AS value FROM market_keyword_metrics "
            "WHERE marketplace = ? AND node_id_path = ? AND grain = 'month' "
            f"AND {column} IS NOT NULL ORDER BY period DESC LIMIT ?",
            (marketplace, node_id_path, limit),
        ))
    return list(reversed(rows))


def upsert_keyword_edges(rows: Iterable[dict]) -> int:
    db._ensure()
    now = _now()
    count = 0
    with db.connect() as conn:
        known = db._table_columns(conn, "market_keyword_asin_edges")
        for item in rows:
            keyword = str(item.get("keyword") or "").strip()
            asin = str(item.get("asin") or "").strip()
            period = str(item.get("period") or "").strip()
            if not (keyword and asin and period):
                continue
            row = {k: v for k, v in item.items() if k in known and k != "id"}
            row.update({
                "id": uuid.uuid4().hex,
                "marketplace": item.get("marketplace", "US"),
                "keyword": keyword, "asin": asin, "period": period,
                "ingested_at": now,
            })
            _upsert(conn, "market_keyword_asin_edges",
                    ("marketplace", "keyword", "asin", "period"), row)
            count += 1
    return count


def keyword_edges(marketplace: str, asin: str, period: str, *, limit: int = 30) -> list[dict]:
    db._ensure()
    with db.connect() as conn:
        return _rows(conn.execute(
            "SELECT * FROM market_keyword_asin_edges WHERE marketplace = ? AND asin = ? "
            "AND period = ? ORDER BY traffic_percentage IS NULL, traffic_percentage DESC "
            "LIMIT ?",
            (marketplace, asin, period, limit),
        ))


# ----------------------------------------------------------------- reviews ----

def element_naming(marketplace: str = "US") -> dict[str, dict]:
    """The model's cached classification of mined terms, keyed by term."""
    db._ensure()
    with db.connect() as conn:
        rows = _rows(conn.execute(
            "SELECT term, kind, label_zh, label_en, dropped, naming_version "
            "FROM market_element_terms WHERE marketplace = ?", (marketplace,)))
    return {row["term"]: {**row, "drop": bool(row["dropped"])} for row in rows}


def save_element_naming(marketplace: str, entries: Iterable[Mapping[str, Any]]) -> int:
    """Upsert the naming for the terms the model answered for.

    An upsert rather than a replace: terms the model was not shown this month
    keep the classification they already had, so a term that drops out of the
    top forty and comes back does not arrive unnamed.
    """
    db._ensure()
    now = _now()
    count = 0
    with db.connect() as conn:
        for entry in entries:
            term = str(entry.get("term") or "").strip().lower()
            if not term:
                continue
            conn.execute(
                "INSERT INTO market_element_terms (marketplace, term, kind, label_zh, "
                "label_en, dropped, naming_version, updated_at) VALUES (?,?,?,?,?,?,?,?) "
                "ON CONFLICT(marketplace, term) DO UPDATE SET kind = excluded.kind, "
                "label_zh = excluded.label_zh, label_en = excluded.label_en, "
                "dropped = excluded.dropped, "
                "naming_version = excluded.naming_version, "
                "updated_at = excluded.updated_at",
                (marketplace, term, str(entry.get("kind") or "other"),
                 str(entry.get("label_zh") or "")[:40],
                 str(entry.get("label_en") or "")[:40],
                 1 if entry.get("drop") else 0,
                 int(entry.get("naming_version") or 0), now),
            )
            count += 1
    return count


def replace_review_themes(
    marketplace: str, node_id_path: str, period: str, themes: Iterable[dict],
    *, asin: str = "",
) -> int:
    """Replace the themed pain points for one node-month.

    Review prose is deliberately not retained: it is third-party text with no
    analytical value once themed, and it would dominate the database. What is kept
    is the theme, its counts, and a few quotes for the evidence drawer.
    """
    db._ensure()
    now = _now()
    count = 0
    with db.connect() as conn:
        conn.execute(
            "DELETE FROM market_review_themes WHERE marketplace = ? AND node_id_path = ? "
            "AND period = ? AND asin = ?",
            (marketplace, node_id_path, period, asin),
        )
        for theme in themes:
            name = str(theme.get("theme") or "").strip()
            if not name:
                continue
            conn.execute(
                "INSERT INTO market_review_themes (id, marketplace, node_id_path, asin, "
                "period, theme, theme_label, category, polarity, severity, "
                "fixable_in_design, return_driving, mention_count, sample_size, "
                "share_of_negative, summary, quotes_json, evidence_ids_json, ingested_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (uuid.uuid4().hex, marketplace, node_id_path, asin, period, name,
                 theme.get("theme_label", name), theme.get("category", "other"),
                 theme.get("polarity", "negative"), theme.get("severity", "minor"),
                 1 if theme.get("fixable_in_design") else 0,
                 1 if theme.get("return_driving") else 0,
                 int(theme.get("mention_count") or 0), int(theme.get("sample_size") or 0),
                 theme.get("share_of_negative"), theme.get("summary", ""),
                 _dumps(theme.get("quotes") or []),
                 _dumps(theme.get("evidence_ids") or []), now),
            )
            count += 1
    return count


def review_themes(marketplace: str, node_id_path: str, period: str) -> list[dict]:
    db._ensure()
    with db.connect() as conn:
        rows = _rows(conn.execute(
            "SELECT * FROM market_review_themes WHERE marketplace = ? AND node_id_path = ? "
            "AND period = ? ORDER BY mention_count DESC",
            (marketplace, node_id_path, period),
        ))
    for row in rows:
        row["quotes"] = _json_load(row.pop("quotes_json", "[]"), [])
        row["evidence_ids"] = _json_load(row.pop("evidence_ids_json", "[]"), [])
        row["fixable_in_design"] = bool(row.get("fixable_in_design"))
        row["return_driving"] = bool(row.get("return_driving"))
    return rows


# ---------------------------------------------------------------- evidence ----

def record_evidence(rows: Iterable[dict]) -> int:
    """Persist evidence rows. Ids are deterministic, so re-ingesting a payload
    updates in place rather than minting a second id for the same number."""
    db._ensure()
    count = 0
    with db.connect() as conn:
        for item in rows:
            eid = str(item.get("id") or "").strip()
            if not eid:
                continue
            conn.execute(
                "INSERT INTO market_evidence (id, marketplace, tool, arguments_json, "
                "field_path, subject_kind, subject_id, metric, period, value_num, "
                "value_text, unit, observed, sample_size, quality, call_id, retrieved_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET value_num = excluded.value_num, "
                "value_text = excluded.value_text, quality = excluded.quality, "
                "sample_size = excluded.sample_size, retrieved_at = excluded.retrieved_at",
                (eid, item.get("marketplace", "US"), item.get("tool", ""),
                 _dumps(item.get("arguments") or {}), item.get("field_path", ""),
                 item.get("subject_kind", ""), item.get("subject_id", ""),
                 item.get("metric", ""), item.get("period", ""), item.get("value_num"),
                 item.get("value_text"), item.get("unit", ""),
                 1 if item.get("observed", True) else 0, item.get("sample_size"),
                 item.get("quality", "ok"), item.get("call_id", ""),
                 item.get("retrieved_at") or _now()),
            )
            count += 1
    return count


def get_evidence(ids: Sequence[str]) -> list[dict]:
    if not ids:
        return []
    db._ensure()
    marks = ", ".join("?" for _ in ids)
    with db.connect() as conn:
        rows = _rows(conn.execute(
            f"SELECT * FROM market_evidence WHERE id IN ({marks})", list(ids)))
    for row in rows:
        row["arguments"] = _json_load(row.pop("arguments_json", "{}"), {})
        row["observed"] = bool(row.get("observed"))
    return rows


def evidence_ids_by_metric(
    marketplace: str, subject_kind: str, subject_id: str, period: str,
    metrics: Sequence[str],
) -> dict[str, str]:
    """Map metric name -> evidence id for one subject-period.

    Deterministic ids are minted from the tool that produced the number, and the
    monitor does not know which tool that was, so it names the metric and looks
    the id up here rather than trying to reconstruct it.
    """
    if not metrics:
        return {}
    db._ensure()
    marks = ", ".join("?" for _ in metrics)
    params: list[Any] = [marketplace, subject_kind, subject_id, period, *metrics]
    with db.connect() as conn:
        rows = _rows(conn.execute(
            f"SELECT metric, id FROM market_evidence WHERE marketplace = ? "
            f"AND subject_kind = ? AND subject_id = ? AND period = ? "
            f"AND metric IN ({marks})",
            params,
        ))
    return {row["metric"]: row["id"] for row in rows}


def evidence_for(
    marketplace: str, subjects: Sequence[tuple[str, str]], period: str, *, limit: int = 600,
) -> list[dict]:
    """Every evidence row backing a set of (subject_kind, subject_id) pairs."""
    if not subjects:
        return []
    db._ensure()
    clause = " OR ".join("(subject_kind = ? AND subject_id = ?)" for _ in subjects)
    params: list[Any] = [marketplace]
    for kind, ident in subjects:
        params += [kind, ident]
    params += [period, limit]
    with db.connect() as conn:
        rows = _rows(conn.execute(
            f"SELECT * FROM market_evidence WHERE marketplace = ? AND ({clause}) "
            f"AND (period = ? OR period = '') ORDER BY subject_kind, metric LIMIT ?",
            params,
        ))
    for row in rows:
        row["arguments"] = _json_load(row.pop("arguments_json", "{}"), {})
        row["observed"] = bool(row.get("observed"))
    return rows


def coverage_counts(marketplace: str, period: str) -> dict[str, int]:
    """How many rows of each vendor data family landed for one period.

    The panel that reports "we are using 19 of the vendor's data types" has to
    read it off the warehouse rather than off the job catalog: a job can be
    marked done and still have written nothing, and a family nobody notices is
    missing is a family nobody notices we stopped paying for.
    """
    db._ensure()
    counts: dict[str, int] = {}
    with db.connect() as conn:
        def scalar(sql: str, params: Sequence[Any]) -> int:
            row = conn.execute(sql, params).fetchone()
            return int(row[0] or 0)

        for family, column in (("category_structure", "total_revenue"),
                               ("category_statistics", "hl_avg_ratings"),
                               ("demand_trend", "return_ratio"),
                               ("fulfilment_mix", "fba_proportion"),
                               ("newcomer_metrics", "new_ratio_l12")):
            counts[family] = scalar(
                f"SELECT COUNT(*) FROM market_node_snapshots WHERE marketplace = ? "
                f"AND period = ? AND {column} IS NOT NULL", (marketplace, period))

        for row in conn.execute(
                "SELECT kind, COUNT(*) AS n FROM market_distributions "
                "WHERE marketplace = ? AND period = ? GROUP BY kind",
                (marketplace, period)):
            counts[f"distribution_{row['kind']}"] = int(row["n"])

        for row in conn.execute(
                "SELECT kind, COUNT(*) AS n FROM market_concentration "
                "WHERE marketplace = ? AND period = ? GROUP BY kind",
                (marketplace, period)):
            counts[f"concentration_{row['kind']}"] = int(row["n"])

        counts["product_research"] = scalar(
            "SELECT COUNT(*) FROM market_product_metrics WHERE marketplace = ? "
            "AND period = ?", (marketplace, period))
        counts["traffic_source"] = scalar(
            "SELECT COUNT(*) FROM market_product_metrics WHERE marketplace = ? "
            "AND period = ? AND natural_proportion IS NOT NULL", (marketplace, period))
        counts["keyword_research"] = scalar(
            "SELECT COUNT(*) FROM market_keyword_metrics WHERE marketplace = ? "
            "AND period = ? AND searches IS NOT NULL", (marketplace, period))
        counts["google_trend"] = scalar(
            "SELECT COUNT(*) FROM market_keyword_metrics WHERE marketplace = ? "
            "AND google_trend_index IS NOT NULL", (marketplace,))
        counts["traffic_keyword"] = scalar(
            "SELECT COUNT(*) FROM market_keyword_asin_edges WHERE marketplace = ? "
            "AND period = ?", (marketplace, period))
        counts["asin_prediction"] = scalar(
            "SELECT COUNT(*) FROM market_product_history WHERE marketplace = ?",
            (marketplace,))
        counts["review"] = scalar(
            "SELECT COUNT(*) FROM market_review_themes WHERE marketplace = ? "
            "AND period = ?", (marketplace, period))
    return counts


# ------------------------------------------------------------ call logging ----

def log_call(
    *, marketplace: str, tool: str, arguments: dict, arguments_hash: str, bucket: str,
    purpose: str, run_date: str, status: str, billable: bool, payload_bytes: int = 0,
    rows_extracted: int = 0, elapsed_ms: int = 0, detail: str | None = None,
) -> str:
    """One row per vendor call. ``billable`` is the budget's unit of account: a
    cache hit and a transport outage cost nothing, a vendor rejection costs a call."""
    db._ensure()
    call_id = uuid.uuid4().hex
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO market_call_log (id, marketplace, tool, arguments_json, "
            "arguments_hash, bucket, purpose, run_date, status, billable, payload_bytes, "
            "rows_extracted, elapsed_ms, detail, called_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (call_id, marketplace, tool, _dumps(arguments), arguments_hash, bucket,
             purpose, run_date, status, 1 if billable else 0, payload_bytes,
             rows_extracted, elapsed_ms, (detail or "")[:300], _now()),
        )
    return call_id


def calls_used(marketplace: str, run_date: str, bucket: str | None = None) -> int:
    """Billable calls spent today, optionally for one wallet."""
    db._ensure()
    sql = ("SELECT COUNT(*) AS n FROM market_call_log "
           "WHERE marketplace = ? AND run_date = ? AND billable = 1")
    params: list[Any] = [marketplace, run_date]
    if bucket:
        sql += " AND bucket = ?"
        params.append(bucket)
    with db.connect() as conn:
        row = conn.execute(sql, params).fetchone()
    return int(row["n"] if row else 0)


def call_log(marketplace: str, run_date: str, *, limit: int = 200) -> list[dict]:
    db._ensure()
    with db.connect() as conn:
        rows = _rows(conn.execute(
            "SELECT * FROM market_call_log WHERE marketplace = ? AND run_date = ? "
            "ORDER BY called_at DESC LIMIT ?",
            (marketplace, run_date, limit),
        ))
    for row in rows:
        row["arguments"] = _json_load(row.pop("arguments_json", "{}"), {})
        row["billable"] = bool(row.get("billable"))
    return rows


# --------------------------------------------------------------- job queue ----

def enqueue_job(
    *, marketplace: str, job_kind: str, subject_kind: str, subject_id: str, period: str,
    priority: int = 100, est_calls: int = 1, next_due_at: float | None = None,
) -> None:
    """Add a job, leave an existing one alone, and wake a parked one.

    A new month reopens work by key: the unique key includes ``period``, so last
    month's completed rows are untouched. The one row that must change is a
    **parked** one — parked means "this month had not closed yet", and the whole
    point is that it eventually does. Without the wake-up, parking a month would
    silently retire it.
    """
    db._ensure()
    now = _now()
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO market_jobs (id, marketplace, job_kind, subject_kind, subject_id, "
            "period, priority, est_calls, next_due_at, status, attempts, created_at, "
            "updated_at) VALUES (?,?,?,?,?,?,?,?,?,'pending',0,?,?) "
            "ON CONFLICT(marketplace, job_kind, subject_kind, subject_id, period) "
            "DO UPDATE SET "
            "  status = CASE WHEN market_jobs.status = 'parked' THEN 'pending' "
            "                ELSE market_jobs.status END, "
            "  attempts = CASE WHEN market_jobs.status = 'parked' THEN 0 "
            "                  ELSE market_jobs.attempts END, "
            "  next_due_at = CASE WHEN market_jobs.status = 'parked' THEN excluded.next_due_at "
            "                     ELSE market_jobs.next_due_at END, "
            "  last_error = CASE WHEN market_jobs.status = 'parked' THEN NULL "
            "                    ELSE market_jobs.last_error END, "
            "  updated_at = excluded.updated_at",
            (uuid.uuid4().hex, marketplace, job_kind, subject_kind, subject_id, period,
             priority, est_calls, next_due_at or now, now, now),
        )


def due_jobs(marketplace: str, *, now: float | None = None, limit: int = 200) -> list[dict]:
    db._ensure()
    with db.connect() as conn:
        return _rows(conn.execute(
            "SELECT * FROM market_jobs WHERE marketplace = ? AND status = 'pending' "
            "AND next_due_at <= ? ORDER BY priority ASC, next_due_at ASC LIMIT ?",
            (marketplace, now or _now(), limit),
        ))


def park_future_jobs(marketplace: str, period: str,
                     *, exempt_kinds: Sequence[str] = ()) -> int:
    """Park pending jobs for months newer than the one being collected.

    The vendor publishes a month's aggregates only after it closes, so jobs
    queued against a month still in progress can never succeed. Left pending
    they are retried three times each before blocking — for twelve nodes that is
    most of a day's budget spent proving that September is not over yet.

    Parked, not deleted: ``plan_period`` re-enqueues the month once it becomes
    the target, and the row keeps its history.
    """
    db._ensure()
    sql = ("UPDATE market_jobs SET status = 'parked', last_error = 'period not closed' "
           "WHERE marketplace = ? AND status = 'pending' AND period > ?")
    params: list[Any] = [marketplace, period]
    if exempt_kinds:
        # The pulse jobs target the open month on purpose; parking them would
        # retire the only view of it that exists.
        sql += f" AND job_kind NOT IN ({', '.join('?' for _ in exempt_kinds)})"
        params += list(exempt_kinds)
    with db.connect() as conn:
        return conn.execute(sql, params).rowcount


def queue_depth(marketplace: str) -> int:
    db._ensure()
    with db.connect() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM market_jobs WHERE marketplace = ? AND status = 'pending'",
            (marketplace,),
        ).fetchone()
    return int(row["n"] if row else 0)


def finish_job(job_id: str, *, status: str, error: str | None = None,
               next_due_at: float | None = None, bump_attempts: bool = False) -> None:
    db._ensure()
    now = _now()
    with db.connect() as conn:
        conn.execute(
            "UPDATE market_jobs SET status = ?, last_error = ?, last_run_at = ?, "
            "updated_at = ?, attempts = attempts + ?, "
            "next_due_at = COALESCE(?, next_due_at) WHERE id = ?",
            (status, (error or "")[:300] or None, now, now,
             1 if bump_attempts else 0, next_due_at, job_id),
        )


# -------------------------------------------------------------------- runs ----

def claim_run(marketplace: str, run_date: str, period: str, budget: int) -> dict | None:
    """Claim today's sweep. Returns the run row, or ``None`` if someone else has it.

    The unique index on (marketplace, run_date) is the lock: ``INSERT OR IGNORE``
    succeeds for exactly one caller, so the sweep is safe under multiple workers
    even though the rest of the scheduler still assumes one.
    """
    db._ensure()
    now = _now()
    run_id = uuid.uuid4().hex
    with db.connect() as conn:
        cursor = conn.execute(
            "INSERT OR IGNORE INTO market_runs (id, marketplace, run_date, period, budget, "
            "status, started_at) VALUES (?,?,?,?,?,'running',?)",
            (run_id, marketplace, run_date, period, budget, now),
        )
        if cursor.rowcount == 0:
            return None
        row = conn.execute("SELECT * FROM market_runs WHERE id = ?", (run_id,)).fetchone()
    return dict(row) if row else None


def finish_run(run_id: str, *, status: str, calls_used: int, jobs_done: int,
               jobs_failed: int, queue_depth_after: int, detail: str = "") -> None:
    db._ensure()
    with db.connect() as conn:
        conn.execute(
            "UPDATE market_runs SET status = ?, calls_used = ?, jobs_done = ?, "
            "jobs_failed = ?, queue_depth = ?, detail = ?, finished_at = ? WHERE id = ?",
            (status, calls_used, jobs_done, jobs_failed, queue_depth_after,
             detail[:300], _now(), run_id),
        )


def latest_run(marketplace: str) -> dict | None:
    db._ensure()
    with db.connect() as conn:
        row = conn.execute(
            "SELECT * FROM market_runs WHERE marketplace = ? ORDER BY started_at DESC LIMIT 1",
            (marketplace,),
        ).fetchone()
    return dict(row) if row else None


# ------------------------------------------------------------------ scores ----

def upsert_scores(rows: Iterable[dict]) -> int:
    db._ensure()
    now = _now()
    count = 0
    with db.connect() as conn:
        for item in rows:
            subject_id = str(item.get("subject_id") or "").strip()
            if not subject_id:
                continue
            _upsert(conn, "market_scores",
                    ("marketplace", "subject_kind", "subject_id", "period"), {
                        "id": uuid.uuid4().hex,
                        "marketplace": item.get("marketplace", "US"),
                        "subject_kind": item.get("subject_kind", "node"),
                        "subject_id": subject_id,
                        "period": item.get("period", ""),
                        "score": float(item.get("score") or 0.0),
                        "confidence": float(item.get("confidence") or 0.0),
                        "breakdown_json": _dumps(item.get("breakdown") or {}),
                        "missing_json": _dumps(item.get("missing") or []),
                        "formula_version": int(item.get("formula_version") or 2),
                        "computed_at": now,
                    })
            count += 1
    return count


def get_scores(marketplace: str, subject_kind: str, period: str) -> list[dict]:
    db._ensure()
    with db.connect() as conn:
        rows = _rows(conn.execute(
            "SELECT * FROM market_scores WHERE marketplace = ? AND subject_kind = ? "
            "AND period = ? ORDER BY score DESC",
            (marketplace, subject_kind, period),
        ))
    for row in rows:
        row["breakdown"] = _json_load(row.pop("breakdown_json", "{}"), {})
        row["missing"] = _json_load(row.pop("missing_json", "[]"), [])
    return rows


# -------------------------------------------------------------- dashboards ----

def save_dashboard(
    *, user_id: str | None, marketplace: str, scope: str, node_id_path: str | None,
    period: str, language: str, status: str, dashboard: dict, summary: str,
    evidence: Sequence[dict], vendor_tools: Sequence[str], data_as_of: float | None,
    completeness: float,
) -> dict:
    db._ensure()
    now = _now()
    dash_id = uuid.uuid4().hex
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO market_dashboards (id, user_id, marketplace, scope, node_id_path, "
            "period, language, status, dashboard_json, summary, evidence_json, "
            "vendor_tools_json, data_as_of, completeness, generated_at, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (dash_id, user_id, marketplace, scope, node_id_path, period, language, status,
             _dumps(dashboard), summary, _dumps(list(evidence)), _dumps(list(vendor_tools)),
             data_as_of, completeness, now, now),
        )
    return get_dashboard(dash_id) or {}


def get_dashboard(dashboard_id: str) -> dict | None:
    db._ensure()
    with db.connect() as conn:
        row = conn.execute(
            "SELECT * FROM market_dashboards WHERE id = ?", (dashboard_id,)).fetchone()
    return _dashboard_row(row) if row else None


def latest_dashboard(
    *, marketplace: str, scope: str, language: str, node_id_path: str | None = None,
    period: str | None = None,
) -> dict | None:
    db._ensure()
    sql = ("SELECT * FROM market_dashboards WHERE marketplace = ? AND scope = ? "
           "AND language = ?")
    params: list[Any] = [marketplace, scope, language]
    if node_id_path:
        sql += " AND node_id_path = ?"
        params.append(node_id_path)
    if period:
        sql += " AND period = ?"
        params.append(period)
    sql += " ORDER BY generated_at DESC LIMIT 1"
    with db.connect() as conn:
        row = conn.execute(sql, params).fetchone()
    return _dashboard_row(row) if row else None


def _dashboard_row(row: sqlite3.Row) -> dict:
    out = dict(row)
    out["dashboard"] = _json_load(out.pop("dashboard_json", "{}"), {})
    out["evidence"] = _json_load(out.pop("evidence_json", "[]"), [])
    out["vendor_tools"] = _json_load(out.pop("vendor_tools_json", "[]"), [])
    return out


# --------------------------------------------------------------- deep dives ----

def get_deepdive(marketplace: str, node_id_path: str, period: str) -> dict | None:
    db._ensure()
    with db.connect() as conn:
        row = conn.execute(
            "SELECT * FROM market_deepdives WHERE marketplace = ? AND node_id_path = ? "
            "AND period = ?",
            (marketplace, node_id_path, period),
        ).fetchone()
    if not row:
        return None
    out = dict(row)
    out["plan"] = _json_load(out.pop("plan_json", "[]"), [])
    return out


def start_deepdive(
    *, marketplace: str, node_id_path: str, period: str, requested_by: str | None,
    calls_budget: int, plan: Sequence[dict],
) -> dict | None:
    """Claim a deep dive for one node-month; ``None`` when one already exists.

    Shared by key, not by user: the second person to ask for the same category in
    the same month reads the stored result and pays nothing.
    """
    db._ensure()
    with db.connect() as conn:
        cursor = conn.execute(
            "INSERT OR IGNORE INTO market_deepdives (id, marketplace, node_id_path, period, "
            "requested_by, status, calls_used, calls_budget, plan_json, started_at) "
            "VALUES (?,?,?,?,?,'running',0,?,?,?)",
            (uuid.uuid4().hex, marketplace, node_id_path, period, requested_by,
             calls_budget, _dumps(list(plan)), _now()),
        )
        if cursor.rowcount == 0:
            return None
    return get_deepdive(marketplace, node_id_path, period)


def finish_deepdive(
    marketplace: str, node_id_path: str, period: str, *, status: str, calls_used: int,
    plan: Sequence[dict], detail: str = "",
) -> None:
    db._ensure()
    with db.connect() as conn:
        conn.execute(
            "UPDATE market_deepdives SET status = ?, calls_used = ?, plan_json = ?, "
            "detail = ?, finished_at = ? WHERE marketplace = ? AND node_id_path = ? "
            "AND period = ?",
            (status, calls_used, _dumps(list(plan)), detail[:300], _now(),
             marketplace, node_id_path, period),
        )


def clear_deepdive(marketplace: str, node_id_path: str, period: str) -> None:
    """Drop the claim so a forced refresh can run again."""
    db._ensure()
    with db.connect() as conn:
        conn.execute(
            "DELETE FROM market_deepdives WHERE marketplace = ? AND node_id_path = ? "
            "AND period = ?",
            (marketplace, node_id_path, period),
        )


# --------------------------------------------------------------------- PRD ----

def add_prd(
    *, user_id: str, marketplace: str, node_id_path: str, period: str, language: str,
    opportunity_id: str, title: str, prd: dict, assumptions: Sequence[str],
    evidence_ids: Sequence[str], notes: Sequence[str],
) -> dict:
    db._ensure()
    now = _now()
    prd_id = uuid.uuid4().hex
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO market_prds (id, user_id, marketplace, node_id_path, period, "
            "language, opportunity_id, title, prd_json, assumptions_json, evidence_json, "
            "notes_json, generated_at, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (prd_id, user_id, marketplace, node_id_path, period, language, opportunity_id,
             title, _dumps(prd), _dumps(list(assumptions)), _dumps(list(evidence_ids)),
             _dumps(list(notes)), now, now),
        )
    return get_prd(prd_id, user_id) or {}


def get_prd(prd_id: str, user_id: str) -> dict | None:
    db._ensure()
    with db.connect() as conn:
        row = conn.execute(
            "SELECT * FROM market_prds WHERE id = ? AND user_id = ?", (prd_id, user_id)
        ).fetchone()
    if not row:
        return None
    out = dict(row)
    out["prd"] = _json_load(out.pop("prd_json", "{}"), {})
    out["assumptions"] = _json_load(out.pop("assumptions_json", "[]"), [])
    out["evidence_ids"] = _json_load(out.pop("evidence_json", "[]"), [])
    out["notes"] = _json_load(out.pop("notes_json", "[]"), [])
    return out


def list_prds(user_id: str, *, limit: int = 50) -> list[dict]:
    db._ensure()
    with db.connect() as conn:
        rows = _rows(conn.execute(
            "SELECT id, node_id_path, period, title, opportunity_id, generated_at "
            "FROM market_prds WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
            (user_id, limit),
        ))
    return rows


def delete_user_market_data(user_id: str) -> None:
    """Drop a user's rendered artifacts. The warehouse itself is global and stays."""
    db._ensure()
    with db.connect() as conn:
        conn.execute("DELETE FROM market_prds WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM market_dashboards WHERE user_id = ?", (user_id,))


# ----------------------------------------------------------------- pruning ----

def prune_market_history(*, retained: int = RETAINED_SNAPSHOTS) -> dict[str, int]:
    """Bound the warehouse to the last ``retained`` monthly snapshots.

    The cutoff comes from the months that actually exist, not from ``now`` minus
    24 months: if the vendor was unreachable for a month, that gap must not
    silently shorten the retained window.

    Idempotent and cheap when there is nothing to do, so the scheduler can call it
    on every tick.
    """
    db._ensure()
    deleted: dict[str, int] = {}
    now = _now()
    with db.connect() as conn:
        # Monthly grain only. A pulse row sits in the month still in progress,
        # which is not a month the vendor has closed; counting it as one shifts
        # the cutoff forward and quietly retains 23 months instead of 24 — the
        # exact silent shortening this function exists to prevent.
        periods = [r["period"] for r in conn.execute(
            "SELECT DISTINCT period FROM market_node_snapshots WHERE grain = ? "
            "ORDER BY period DESC", (MONTH,))]
        if len(periods) > retained:
            cutoff = periods[retained - 1]
            for table, column in _PERIOD_TABLES:
                cursor = conn.execute(
                    f"DELETE FROM {table} WHERE {column} != '' AND {column} < ?", (cutoff,))
                if cursor.rowcount:
                    deleted[table] = cursor.rowcount
            # Evidence outlives its facts only as clutter.
            cursor = conn.execute(
                "DELETE FROM market_evidence WHERE period != '' AND period < ?", (cutoff,))
            if cursor.rowcount:
                deleted["market_evidence"] = cursor.rowcount
            # Keep the newest global dashboard per language whatever its age: the
            # homepage must never 404 because the warehouse rolled forward.
            cursor = conn.execute(
                "DELETE FROM market_dashboards WHERE period < ? AND id NOT IN ("
                "  SELECT id FROM ("
                "    SELECT id, ROW_NUMBER() OVER ("
                "      PARTITION BY scope, language, COALESCE(node_id_path, '') "
                "      ORDER BY generated_at DESC) AS rn"
                "    FROM market_dashboards) WHERE rn = 1)",
                (cutoff,),
            )
            if cursor.rowcount:
                deleted["market_dashboards"] = cursor.rowcount

        # Call log: the payload column is the bulk, and it is only there so a fixed
        # extractor can re-parse without re-paying.
        cursor = conn.execute(
            "DELETE FROM market_call_log WHERE called_at < ?",
            (now - RUN_LOG_TTL_DAYS * 86400,))
        if cursor.rowcount:
            deleted["market_call_log"] = cursor.rowcount
        cursor = conn.execute(
            "DELETE FROM market_runs WHERE started_at < ?",
            (now - RUN_LOG_TTL_DAYS * 86400,))
        if cursor.rowcount:
            deleted["market_runs"] = cursor.rowcount

        # Dimension rows with no surviving facts. Nodes are never pruned: they are
        # the stable spine, they cost nothing, and re-resolving one costs a call.
        cursor = conn.execute(
            "DELETE FROM market_products WHERE NOT EXISTS ("
            "  SELECT 1 FROM market_product_metrics m "
            "  WHERE m.marketplace = market_products.marketplace AND m.asin = market_products.asin)")
        if cursor.rowcount:
            deleted["market_products"] = cursor.rowcount
    return deleted
