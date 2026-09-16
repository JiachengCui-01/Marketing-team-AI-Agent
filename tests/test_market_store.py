"""Warehouse persistence: upsert semantics, the daily budget ledger, and retention.

Offline throughout — nothing here touches a vendor or a model.
"""
from __future__ import annotations

import time
import unittest

from server import db
from server.market import store


# The shape this table had before ``grain`` existed, written out rather than
# derived, so the test keeps reproducing the old database even after the live
# schema moves on again.
_PRE_GRAIN_SNAPSHOTS = """
DROP TABLE IF EXISTS market_node_snapshots;
CREATE TABLE market_node_snapshots (
    id TEXT PRIMARY KEY,
    marketplace TEXT NOT NULL DEFAULT 'US',
    node_id_path TEXT NOT NULL,
    period TEXT NOT NULL,
    avg_price REAL,
    total_revenue REAL,
    total_products INTEGER,
    completeness REAL NOT NULL DEFAULT 0.0,
    missing_json TEXT NOT NULL DEFAULT '[]',
    schema_version INTEGER NOT NULL DEFAULT 1,
    ingested_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE UNIQUE INDEX idx_market_node_snapshots_key
    ON market_node_snapshots(marketplace, node_id_path, period);
"""


# Likewise for the keyword table before the growth windows were split apart.
_PRE_GROWTH_KEYWORDS = """
DROP TABLE IF EXISTS market_keyword_metrics;
CREATE TABLE market_keyword_metrics (
    id TEXT PRIMARY KEY,
    marketplace TEXT NOT NULL DEFAULT 'US',
    keyword TEXT NOT NULL,
    node_id_path TEXT,
    period TEXT NOT NULL,
    grain TEXT NOT NULL DEFAULT 'month',
    searches REAL, searches_growth REAL,
    search_rank INTEGER, rank_growth_rate REAL,
    purchases REAL, purchase_rate REAL,
    supply_demand_ratio REAL, monopoly_click_rate REAL,
    spr REAL, title_density REAL,
    products REAL, avg_price REAL, bid REAL, bid_max REAL,
    market_period TEXT,
    google_trend_index REAL,
    source_tool TEXT NOT NULL DEFAULT '',
    evidence_id TEXT,
    ingested_at REAL NOT NULL
);
"""


# And the element naming table before the kind vocabulary was versioned.
_PRE_VERSION_ELEMENT_TERMS = """
DROP TABLE IF EXISTS market_element_terms;
CREATE TABLE market_element_terms (
    marketplace TEXT NOT NULL DEFAULT 'US',
    term TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'other',
    label_zh TEXT NOT NULL DEFAULT '',
    label_en TEXT NOT NULL DEFAULT '',
    dropped INTEGER NOT NULL DEFAULT 0,
    updated_at REAL NOT NULL,
    PRIMARY KEY (marketplace, term)
);
"""


class SchemaUpgradeTests(unittest.TestCase):
    """``init()`` must survive meeting a database from an earlier release.

    This is the failure mode that takes a deployment down rather than degrading
    it. ``init()`` runs the schema script before the migrations, so a statement
    in the script that references a column only a migration adds raises on every
    existing database — and ``_ensure()`` runs on the first query of every
    request, so the entire API 500s and nobody can even log in.
    """

    NODE = "1055398:1063306:3733781:3733831"

    def _downgrade(self) -> None:
        db.reset_for_tests()
        db.init()
        with db.connect() as conn:
            conn.executescript(_PRE_GRAIN_SNAPSHOTS)
            self.assertNotIn("grain", db._table_columns(conn, "market_node_snapshots"))
        db._INITIALIZED = False

    def tearDown(self) -> None:
        db.reset_for_tests()

    def test_init_upgrades_a_database_that_predates_the_grain_column(self) -> None:
        self._downgrade()

        db.init()                      # must not raise

        with db.connect() as conn:
            columns = db._table_columns(conn, "market_node_snapshots")
            indexes = {r["name"] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index' "
                "AND tbl_name = 'market_node_snapshots'")}
        self.assertIn("grain", columns)
        self.assertIn("observed_at", columns)
        # Added by the same migration path; the depth figure the coverage tile
        # reads would otherwise be filtered out against the table's column list.
        self.assertIn("product_pool", columns)
        self.assertIn("product_tail_pct", columns)
        self.assertIn("idx_market_node_snapshots_grain", indexes)
        # The old key would reject a pulse row sharing a month with its aggregate.
        self.assertNotIn("idx_market_node_snapshots_key", indexes)

    def test_init_upgrades_a_database_that_predates_the_growth_windows(self) -> None:
        """The columns the element matrix reads are added by migration, not schema."""
        db.reset_for_tests()
        db.init()
        with db.connect() as conn:
            conn.executescript(_PRE_GROWTH_KEYWORDS)
            self.assertNotIn("searches_mom_pct",
                             db._table_columns(conn, "market_keyword_metrics"))
        db._INITIALIZED = False

        db.init()                      # must not raise

        with db.connect() as conn:
            columns = db._table_columns(conn, "market_keyword_metrics")
        for name in ("searches_mom_pct", "searches_yoy_pct", "rank_4w", "rank_12w"):
            self.assertIn(name, columns)

    def test_an_upgraded_keyword_table_still_accepts_writes(self) -> None:
        """A column added but never written to is a migration that only looks done."""
        db.reset_for_tests()
        db.init()
        with db.connect() as conn:
            conn.executescript(_PRE_GROWTH_KEYWORDS)
        db._INITIALIZED = False
        db.init()

        store.upsert_keyword_metrics([{
            "marketplace": "US", "keyword": "fluted sideboard", "period": "202608",
            "node_id_path": self.NODE, "searches": 11_000.0,
            "searches_mom_pct": 12.5, "searches_yoy_pct": 41.0,
            "rank_4w": 940, "rank_12w": 1220, "source_tool": "keyword_research",
        }])
        row = store.top_keywords("US", self.NODE, "202608")[0]
        self.assertEqual(row["searches_mom_pct"], 12.5)
        self.assertEqual(row["rank_12w"], 1220)

    def test_init_upgrades_a_database_that_predates_the_naming_version(self) -> None:
        """A classification cached before `craft` and `color` existed was made
        from a shorter menu, so it has to be re-asked rather than trusted."""
        db.reset_for_tests()
        db.init()
        now = time.time()
        with db.connect() as conn:
            conn.executescript(_PRE_VERSION_ELEMENT_TERMS)
            self.assertNotIn("naming_version",
                             db._table_columns(conn, "market_element_terms"))
            conn.execute(
                "INSERT INTO market_element_terms (marketplace, term, kind, "
                "label_zh, label_en, dropped, updated_at) "
                "VALUES ('US', 'fluted', 'style', '竖纹', 'Fluted', 0, ?)", (now,))
        db._INITIALIZED = False

        db.init()                      # must not raise

        with db.connect() as conn:
            self.assertIn("naming_version",
                          db._table_columns(conn, "market_element_terms"))
        cached = store.element_naming("US")["fluted"]
        # Kept, so nothing goes unlabelled in the meantime; stamped 0, so the
        # next render asks again under the vocabulary that has a craft column.
        self.assertEqual(cached["kind"], "style")
        self.assertEqual(cached["naming_version"], 0)

    def test_an_upgraded_element_table_still_accepts_writes(self) -> None:
        db.reset_for_tests()
        db.init()
        with db.connect() as conn:
            conn.executescript(_PRE_VERSION_ELEMENT_TERMS)
        db._INITIALIZED = False
        db.init()

        store.save_element_naming("US", [
            {"term": "burl", "kind": "craft", "label_zh": "木瘤纹",
             "label_en": "Burl", "drop": False, "naming_version": 2}])
        cached = store.element_naming("US")["burl"]
        self.assertEqual(cached["kind"], "craft")
        self.assertEqual(cached["naming_version"], 2)

    def test_rows_predating_the_column_become_monthly_rows(self) -> None:
        """The default has to backfill, or the board loses every month it had."""
        self._downgrade()
        now = time.time()
        with db.connect() as conn:
            conn.execute(
                "INSERT INTO market_node_snapshots (id, marketplace, node_id_path, "
                "period, total_revenue, ingested_at, updated_at) "
                "VALUES ('x', 'US', ?, '202608', 6907337.97, ?, ?)",
                (self.NODE, now, now))

        db.init()

        snapshot = store.get_node_snapshot("US", self.NODE, "202608")
        self.assertIsNotNone(snapshot)
        self.assertEqual(snapshot["grain"], "month")
        self.assertEqual(store.latest_period("US"), "202608")

    def test_the_upgraded_table_accepts_a_pulse_beside_its_aggregate(self) -> None:
        """Same node, same month, two grains — impossible under the old key."""
        self._downgrade()
        db.init()
        store.upsert_node_snapshot("US", self.NODE, "202609", {"total_revenue": 1.0})
        store.upsert_node_snapshot("US", self.NODE, "202609", {"avg_price": 2.0},
                                   grain=store.PULSE)
        self.assertEqual(
            store.get_node_snapshot("US", self.NODE, "202609")["total_revenue"], 1.0)
        self.assertEqual(
            store.get_node_snapshot("US", self.NODE, "202609",
                                    grain=store.PULSE)["avg_price"], 2.0)

    def test_initialising_twice_changes_nothing(self) -> None:
        db.reset_for_tests()
        db.init()
        db._INITIALIZED = False
        db.init()      # idempotent: the scheduler and the tests both re-enter it


class MarketStoreTests(unittest.TestCase):
    NODE = "1055398:1063306:3733781:3733831"
    LABEL = "Home & Kitchen:Furniture:Kitchen & Dining Room Furniture:Buffets & Sideboards"

    def setUp(self) -> None:
        db.reset_for_tests()
        store.upsert_nodes([{
            "marketplace": "US", "node_id_path": self.NODE, "node_label_path": self.LABEL,
            "brand_category": "storage cabinets and sideboards", "tracked": True,
            "tier": 1, "products": 4210,
        }])

    def tearDown(self) -> None:
        db.reset_for_tests()

    # ----- schema / taxonomy -------------------------------------------------

    def test_init_is_idempotent(self) -> None:
        db.init()
        db._INITIALIZED = False
        db.init()  # would raise on a duplicate CREATE without IF NOT EXISTS
        self.assertEqual(len(store.list_nodes("US")), 1)

    def test_node_label_and_depth_are_derived_from_the_path(self) -> None:
        node = store.get_node("US", self.NODE)
        self.assertEqual(node["label"], "Buffets & Sideboards")
        self.assertEqual(node["depth"], 3)
        self.assertEqual(node["parent_path"], "1055398:1063306:3733781")
        self.assertEqual(node["tier"], 1)

    def test_untracked_nodes_are_hidden_from_the_sweep_list(self) -> None:
        store.upsert_nodes([{"marketplace": "US", "node_id_path": "1:2",
                             "node_label_path": "Office Products:Chairs"}])
        self.assertEqual(len(store.list_nodes("US")), 1)
        self.assertEqual(len(store.list_nodes("US", tracked_only=False)), 2)

    # ----- snapshots ---------------------------------------------------------

    def test_a_partial_refetch_fills_gaps_without_blanking_landed_columns(self) -> None:
        """The whole reason upserts use COALESCE: two jobs fill one month's row."""
        store.upsert_node_snapshot("US", self.NODE, "202608",
                                   {"avg_price": 512.0, "total_revenue": 1_240_000.0},
                                   completeness=0.5, missing=["price_distribution"])
        store.upsert_node_snapshot("US", self.NODE, "202608",
                                   {"return_ratio": 0.081, "return_ratio_avg": 0.063},
                                   completeness=1.0, missing=[])
        snap = store.get_node_snapshot("US", self.NODE, "202608")
        self.assertAlmostEqual(snap["avg_price"], 512.0)          # survived pass two
        self.assertAlmostEqual(snap["return_ratio"], 0.081)       # added by pass two
        self.assertAlmostEqual(snap["completeness"], 1.0)
        self.assertEqual(snap["missing"], [])

    def test_unknown_metric_keys_are_dropped_not_raised(self) -> None:
        store.upsert_node_snapshot("US", self.NODE, "202608",
                                   {"avg_price": 1.0, "a_field_the_vendor_just_invented": 9})
        self.assertIsNotNone(store.get_node_snapshot("US", self.NODE, "202608"))

    def test_snapshot_history_is_oldest_first(self) -> None:
        for period, revenue in (("202606", 1.0), ("202607", 2.0), ("202608", 3.0)):
            store.upsert_node_snapshot("US", self.NODE, period, {"total_revenue": revenue})
        series = store.snapshot_history("US", self.NODE)
        self.assertEqual([r["period"] for r in series], ["202606", "202607", "202608"])

    def test_list_node_snapshots_joins_the_node_label(self) -> None:
        store.upsert_node_snapshot("US", self.NODE, "202608", {"total_revenue": 5.0})
        rows = store.list_node_snapshots("US", "202608")
        self.assertEqual(rows[0]["node_label_path"], self.LABEL)
        self.assertEqual(rows[0]["brand_category"], "storage cabinets and sideboards")

    # ----- distributions / concentration -------------------------------------

    def test_distribution_is_replaced_not_merged(self) -> None:
        """A bucket that left the vendor reply left the market; keeping it would
        make the shares stop summing to 100%."""
        store.replace_distribution("US", self.NODE, "202608", "price", [
            {"bucket_key": "$0-$100", "products": 10, "units_ratio": 0.1},
            {"bucket_key": "$100-$200", "products": 20, "units_ratio": 0.9},
        ])
        store.replace_distribution("US", self.NODE, "202608", "price", [
            {"bucket_key": "$100-$200", "products": 25, "units_ratio": 1.0},
        ])
        rows = store.get_distribution("US", self.NODE, "202608", "price")
        self.assertEqual([r["bucket_key"] for r in rows], ["$100-$200"])
        self.assertEqual(rows[0]["products"], 25)

    def test_distribution_keeps_vendor_bucket_order(self) -> None:
        store.replace_distribution("US", self.NODE, "202608", "price", [
            {"bucket_key": "c"}, {"bucket_key": "a"}, {"bucket_key": "b"}])
        rows = store.get_distribution("US", self.NODE, "202608", "price")
        self.assertEqual([r["bucket_key"] for r in rows], ["c", "a", "b"])

    def test_concentration_ranks_default_to_reply_order(self) -> None:
        store.replace_concentration("US", self.NODE, "202608", "brand", [
            {"entity": "Brand A", "revenue_ratio": 0.09},
            {"entity": "Brand B", "revenue_ratio": 0.07},
        ])
        rows = store.get_concentration("US", self.NODE, "202608", "brand")
        self.assertEqual([r["rank"] for r in rows], [1, 2])
        self.assertEqual(rows[0]["entity"], "Brand A")

    # ----- products / keywords / reviews -------------------------------------

    def test_top_products_joins_the_dimension_and_orders_by_revenue(self) -> None:
        store.upsert_products([
            {"marketplace": "US", "asin": "B01", "title": "Oak sideboard", "brand": "A"},
            {"marketplace": "US", "asin": "B02", "title": "Walnut buffet", "brand": "B"},
        ])
        store.upsert_product_metrics([
            {"marketplace": "US", "asin": "B01", "period": "202608",
             "node_id_path": self.NODE, "revenue": 100.0},
            {"marketplace": "US", "asin": "B02", "period": "202608",
             "node_id_path": self.NODE, "revenue": 900.0},
        ])
        rows = store.top_products("US", self.NODE, "202608")
        self.assertEqual([r["asin"] for r in rows], ["B02", "B01"])
        self.assertEqual(rows[0]["title"], "Walnut buffet")

    def test_first_seen_survives_a_later_sighting(self) -> None:
        store.upsert_products([{"marketplace": "US", "asin": "B01", "title": "v1"}])
        first = store.top_products("US", self.NODE, "202608")
        time.sleep(0.01)
        store.upsert_products([{"marketplace": "US", "asin": "B01", "title": "v2"}])
        with db.connect() as conn:
            row = conn.execute(
                "SELECT first_seen_at, last_seen_at, title FROM market_products "
                "WHERE asin = 'B01'").fetchone()
        self.assertEqual(row["title"], "v2")
        self.assertLess(row["first_seen_at"], row["last_seen_at"])
        self.assertEqual(first, [])  # no metrics row yet, so nothing to rank

    def test_product_history_is_oldest_first(self) -> None:
        store.upsert_product_history([
            {"marketplace": "US", "asin": "B01", "period": "202607", "metric": "units",
             "value": 10.0, "observed": False, "source_tool": "asin_prediction"},
            {"marketplace": "US", "asin": "B01", "period": "202608", "metric": "units",
             "value": 12.0, "observed": False, "source_tool": "asin_prediction"},
        ])
        series = store.product_history("US", "B01", "units")
        self.assertEqual([p["period"] for p in series], ["202607", "202608"])
        self.assertEqual(series[0]["observed"], 0)

    def test_keyword_metrics_and_edges_round_trip(self) -> None:
        store.upsert_keyword_metrics([{
            "marketplace": "US", "keyword": "sideboard buffet cabinet", "period": "202608",
            "node_id_path": self.NODE, "searches": 74000, "supply_demand_ratio": 8.3,
        }])
        store.upsert_keyword_edges([{
            "marketplace": "US", "keyword": "sideboard buffet cabinet", "asin": "B01",
            "period": "202608", "traffic_percentage": 0.12, "natural_ratio": 0.6,
        }])
        self.assertEqual(store.top_keywords("US", self.NODE, "202608")[0]["searches"], 74000)
        self.assertAlmostEqual(
            store.keyword_edges("US", "B01", "202608")[0]["traffic_percentage"], 0.12)

    def test_review_themes_round_trip_with_flags_and_quotes(self) -> None:
        store.replace_review_themes("US", self.NODE, "202608", [{
            "theme": "damage_in_transit", "theme_label": "运输磕碰",
            "category": "damage_in_transit", "severity": "blocking",
            "fixable_in_design": True, "return_driving": True,
            "mention_count": 71, "sample_size": 230, "share_of_negative": 0.31,
            "quotes": ["corner arrived crushed"], "evidence_ids": ["ev_1"],
        }])
        theme = store.review_themes("US", self.NODE, "202608")[0]
        self.assertTrue(theme["fixable_in_design"])
        self.assertTrue(theme["return_driving"])
        self.assertEqual(theme["quotes"], ["corner arrived crushed"])
        self.assertEqual(theme["evidence_ids"], ["ev_1"])

    # ----- evidence ----------------------------------------------------------

    def test_evidence_is_upserted_by_id_not_duplicated(self) -> None:
        row = {"id": "ev_abc", "marketplace": "US", "tool": "market_research",
               "field_path": "$.data.items[0].avgPrice", "subject_kind": "node",
               "subject_id": self.NODE, "metric": "avg_price", "period": "202608",
               "value_num": 512.0, "unit": "USD", "observed": True}
        store.record_evidence([row])
        store.record_evidence([{**row, "value_num": 518.0}])
        found = store.get_evidence(["ev_abc"])
        self.assertEqual(len(found), 1)
        self.assertAlmostEqual(found[0]["value_num"], 518.0)
        self.assertTrue(found[0]["observed"])

    def test_evidence_for_selects_by_subject_and_period(self) -> None:
        store.record_evidence([
            {"id": "ev_1", "subject_kind": "node", "subject_id": self.NODE,
             "metric": "avg_price", "period": "202608", "tool": "market_research",
             "field_path": "a", "value_num": 1.0},
            {"id": "ev_2", "subject_kind": "node", "subject_id": self.NODE,
             "metric": "avg_price", "period": "202607", "tool": "market_research",
             "field_path": "a", "value_num": 2.0},
            {"id": "ev_3", "subject_kind": "asin", "subject_id": "B01",
             "metric": "price", "period": "202608", "tool": "product_research",
             "field_path": "b", "value_num": 3.0},
        ])
        ids = {e["id"] for e in store.evidence_for("US", [("node", self.NODE)], "202608")}
        self.assertEqual(ids, {"ev_1"})

    # ----- budget ledger -----------------------------------------------------

    def test_only_billable_calls_count_against_the_day(self) -> None:
        for status, billable in (("ok", True), ("rejected", True), ("cached", False),
                                 ("unavailable", False)):
            store.log_call(marketplace="US", tool="market_research", arguments={},
                           arguments_hash="h", bucket="sweep", purpose="p",
                           run_date="2026-09-11", status=status, billable=billable)
        self.assertEqual(store.calls_used("US", "2026-09-11"), 2)

    def test_wallets_are_counted_independently(self) -> None:
        store.log_call(marketplace="US", tool="t", arguments={}, arguments_hash="h",
                       bucket="sweep", purpose="p", run_date="d", status="ok", billable=True)
        store.log_call(marketplace="US", tool="t", arguments={}, arguments_hash="h",
                       bucket="deepdive", purpose="p", run_date="d", status="ok", billable=True)
        self.assertEqual(store.calls_used("US", "d", "sweep"), 1)
        self.assertEqual(store.calls_used("US", "d", "deepdive"), 1)
        self.assertEqual(store.calls_used("US", "d"), 2)

    # ----- job queue ---------------------------------------------------------

    def test_enqueue_is_idempotent_per_key(self) -> None:
        for _ in range(3):
            store.enqueue_job(marketplace="US", job_kind="category_structure",
                              subject_kind="node", subject_id=self.NODE, period="202608")
        self.assertEqual(store.queue_depth("US"), 1)

    def test_a_new_period_reopens_work_without_touching_last_month(self) -> None:
        store.enqueue_job(marketplace="US", job_kind="k", subject_kind="node",
                          subject_id=self.NODE, period="202607")
        job = store.due_jobs("US")[0]
        store.finish_job(job["id"], status="done")
        store.enqueue_job(marketplace="US", job_kind="k", subject_kind="node",
                          subject_id=self.NODE, period="202608")
        due = store.due_jobs("US")
        self.assertEqual([j["period"] for j in due], ["202608"])

    def test_due_jobs_respect_priority_then_backoff(self) -> None:
        store.enqueue_job(marketplace="US", job_kind="low", subject_kind="node",
                          subject_id="n1", period="p", priority=90)
        store.enqueue_job(marketplace="US", job_kind="high", subject_kind="node",
                          subject_id="n2", period="p", priority=10)
        store.enqueue_job(marketplace="US", job_kind="later", subject_kind="node",
                          subject_id="n3", period="p", priority=1,
                          next_due_at=time.time() + 3600)
        # Read the clock after enqueueing: a job stamped a millisecond from now is
        # due, and on Windows time.time() is coarse enough for the order to matter.
        kinds = [j["job_kind"] for j in store.due_jobs("US", now=time.time())]
        self.assertEqual(kinds, ["high", "low"])  # "later" is backed off

    def test_finish_job_bumps_attempts_only_when_asked(self) -> None:
        store.enqueue_job(marketplace="US", job_kind="k", subject_kind="node",
                          subject_id="n", period="p")
        job = store.due_jobs("US")[0]
        store.finish_job(job["id"], status="pending", error="rejected",
                         next_due_at=time.time() + 3600, bump_attempts=True)
        with db.connect() as conn:
            row = conn.execute("SELECT attempts, last_error FROM market_jobs WHERE id = ?",
                               (job["id"],)).fetchone()
        self.assertEqual(row["attempts"], 1)
        self.assertEqual(row["last_error"], "rejected")

    # ----- run claim ---------------------------------------------------------

    def test_only_one_caller_claims_a_sweep_day(self) -> None:
        first = store.claim_run("US", "2026-09-11", "202609", 45)
        second = store.claim_run("US", "2026-09-11", "202609", 45)
        self.assertIsNotNone(first)
        self.assertIsNone(second)
        store.finish_run(first["id"], status="complete", calls_used=45, jobs_done=12,
                         jobs_failed=0, queue_depth_after=157)
        latest = store.latest_run("US")
        self.assertEqual(latest["status"], "complete")
        self.assertEqual(latest["queue_depth"], 157)

    # ----- scores / dashboards / deepdives / prd -----------------------------

    def test_scores_upsert_by_subject_and_period(self) -> None:
        store.upsert_scores([{"marketplace": "US", "subject_kind": "node",
                              "subject_id": self.NODE, "period": "202608", "score": 71.0,
                              "confidence": 0.9, "breakdown": {"demand_scale": 8.1},
                              "missing": ["keyword_sdr"]}])
        store.upsert_scores([{"marketplace": "US", "subject_kind": "node",
                              "subject_id": self.NODE, "period": "202608", "score": 73.0,
                              "breakdown": {"demand_scale": 9.0}}])
        rows = store.get_scores("US", "node", "202608")
        self.assertEqual(len(rows), 1)
        self.assertAlmostEqual(rows[0]["score"], 73.0)
        self.assertEqual(rows[0]["breakdown"], {"demand_scale": 9.0})

    def test_latest_dashboard_is_scoped_by_language_and_node(self) -> None:
        for language in ("zh", "en"):
            store.save_dashboard(user_id=None, marketplace="US", scope="overview",
                                 node_id_path=None, period="202608", language=language,
                                 status="ok", dashboard={"board": [language]}, summary="s",
                                 evidence=[], vendor_tools=["market_research"],
                                 data_as_of=1.0, completeness=1.0)
        zh = store.latest_dashboard(marketplace="US", scope="overview", language="zh")
        self.assertEqual(zh["dashboard"]["board"], ["zh"])
        self.assertEqual(zh["vendor_tools"], ["market_research"])
        self.assertIsNone(
            store.latest_dashboard(marketplace="US", scope="category", language="zh"))

    def test_a_deepdive_is_claimed_once_per_node_month(self) -> None:
        first = store.start_deepdive(marketplace="US", node_id_path=self.NODE,
                                     period="202608", requested_by="u1", calls_budget=40,
                                     plan=[{"step": "product_research"}])
        second = store.start_deepdive(marketplace="US", node_id_path=self.NODE,
                                      period="202608", requested_by="u2", calls_budget=40,
                                      plan=[])
        self.assertIsNotNone(first)
        self.assertIsNone(second)  # the second asker reads the stored result, pays nothing
        store.finish_deepdive("US", self.NODE, "202608", status="partial", calls_used=22,
                              plan=[{"step": "product_research", "status": "done"}])
        dive = store.get_deepdive("US", self.NODE, "202608")
        self.assertEqual(dive["status"], "partial")
        self.assertEqual(dive["calls_used"], 22)
        self.assertEqual(dive["plan"][0]["status"], "done")

    def test_prd_round_trip_is_user_scoped(self) -> None:
        user = db.create_user(account="a@example.com", password_hash="x", username="u",
                              real_name="r", id_card="", avatar=None)
        prd = store.add_prd(user_id=user["id"], marketplace="US", node_id_path=self.NODE,
                            period="202608", language="zh", opportunity_id="op1",
                            title="60 英寸窄进深餐边柜", prd={"positioning": "…"},
                            assumptions=["模型推断（未经证据支持）：…"],
                            evidence_ids=["ev_1"], notes=[])
        self.assertEqual(store.get_prd(prd["id"], user["id"])["title"], "60 英寸窄进深餐边柜")
        self.assertIsNone(store.get_prd(prd["id"], "someone-else"))
        self.assertEqual(len(store.list_prds(user["id"])), 1)

    def test_deleting_a_user_keeps_the_global_warehouse(self) -> None:
        user = db.create_user(account="b@example.com", password_hash="x", username="u",
                              real_name="r", id_card="", avatar=None)
        store.add_prd(user_id=user["id"], marketplace="US", node_id_path=self.NODE,
                      period="202608", language="zh", opportunity_id="op", title="t",
                      prd={}, assumptions=[], evidence_ids=[], notes=[])
        store.upsert_node_snapshot("US", self.NODE, "202608", {"avg_price": 1.0})
        store.delete_user_market_data(user["id"])
        self.assertEqual(store.list_prds(user["id"]), [])
        self.assertIsNotNone(store.get_node_snapshot("US", self.NODE, "202608"))

    # ----- retention ---------------------------------------------------------

    def test_pruning_keeps_the_last_24_months_and_orphans_nothing(self) -> None:
        periods = [f"2024{m:02d}" for m in range(1, 13)] + \
                  [f"2025{m:02d}" for m in range(1, 13)] + ["202601", "202602"]
        self.assertEqual(len(periods), 26)
        for period in periods:
            store.upsert_node_snapshot("US", self.NODE, period, {"avg_price": 1.0})
            store.record_evidence([{"id": f"ev_{period}", "marketplace": "US",
                                    "tool": "market_research", "field_path": "a",
                                    "subject_kind": "node", "subject_id": self.NODE,
                                    "metric": "avg_price", "period": period,
                                    "value_num": 1.0}])
        store.prune_market_history()
        with db.connect() as conn:
            kept = [r["period"] for r in conn.execute(
                "SELECT DISTINCT period FROM market_node_snapshots ORDER BY period")]
            evidence = [r["period"] for r in conn.execute(
                "SELECT DISTINCT period FROM market_evidence ORDER BY period")]
        self.assertEqual(len(kept), 24)
        self.assertNotIn("202401", kept)
        self.assertIn("202602", kept)
        self.assertEqual(kept, evidence)  # no evidence outlives its facts

    def test_a_vendor_outage_month_does_not_shorten_the_window(self) -> None:
        """The cutoff comes from the months that exist, not from a calendar subtraction."""
        periods = ["202401", "202402"] + [f"2025{m:02d}" for m in range(1, 13)]
        for period in periods:
            store.upsert_node_snapshot("US", self.NODE, period, {"avg_price": 1.0})
        store.prune_market_history()
        with db.connect() as conn:
            kept = [r["period"] for r in conn.execute(
                "SELECT DISTINCT period FROM market_node_snapshots ORDER BY period")]
        self.assertEqual(len(kept), 14)  # fewer than 24 exist, so nothing is dropped
        self.assertIn("202401", kept)

    def test_a_live_pulse_does_not_shorten_the_retained_window(self) -> None:
        """A pulse sits in the month still in progress, which is not a closed
        month; counting it as one retains 23 months while claiming 24."""
        periods = [f"2024{m:02d}" for m in range(1, 13)] +                   [f"2025{m:02d}" for m in range(1, 13)]
        for period in periods:
            store.upsert_node_snapshot("US", self.NODE, period, {"avg_price": 1.0})
        store.upsert_node_snapshot("US", self.NODE, "202601", {"avg_price": 2.0},
                                   grain=store.PULSE)
        store.prune_market_history()
        with db.connect() as conn:
            kept = [r["period"] for r in conn.execute(
                "SELECT DISTINCT period FROM market_node_snapshots "
                "WHERE grain = 'month' ORDER BY period")]
        self.assertEqual(len(kept), 24)
        self.assertIn("202401", kept)
        self.assertIsNotNone(
            store.get_node_snapshot("US", self.NODE, "202601", grain=store.PULSE))

    def test_a_pulse_from_a_dropped_month_goes_with_it(self) -> None:
        """Last year's live reading is not worth keeping once its month is gone."""
        periods = [f"2024{m:02d}" for m in range(1, 13)] +                   [f"2025{m:02d}" for m in range(1, 13)] + ["202601", "202602"]
        for period in periods:
            store.upsert_node_snapshot("US", self.NODE, period, {"avg_price": 1.0})
        store.upsert_node_snapshot("US", self.NODE, "202401", {"avg_price": 2.0},
                                   grain=store.PULSE)
        store.prune_market_history()
        self.assertIsNone(
            store.get_node_snapshot("US", self.NODE, "202401", grain=store.PULSE))

    def test_pruning_is_idempotent_and_cheap_when_there_is_nothing_to_do(self) -> None:
        store.upsert_node_snapshot("US", self.NODE, "202608", {"avg_price": 1.0})
        self.assertEqual(store.prune_market_history(), {})
        self.assertEqual(store.prune_market_history(), {})

    def test_pruning_keeps_the_newest_dashboard_per_language(self) -> None:
        for period in ("202401", "202602"):
            for language in ("zh", "en"):
                store.save_dashboard(user_id=None, marketplace="US", scope="overview",
                                     node_id_path=None, period=period, language=language,
                                     status="ok", dashboard={}, summary="", evidence=[],
                                     vendor_tools=[], data_as_of=None, completeness=1.0)
        for month in range(1, 13):
            store.upsert_node_snapshot("US", self.NODE, f"2024{month:02d}", {"avg_price": 1.0})
            store.upsert_node_snapshot("US", self.NODE, f"2025{month:02d}", {"avg_price": 1.0})
        store.upsert_node_snapshot("US", self.NODE, "202601", {"avg_price": 1.0})
        store.upsert_node_snapshot("US", self.NODE, "202602", {"avg_price": 1.0})
        store.prune_market_history()
        self.assertIsNotNone(
            store.latest_dashboard(marketplace="US", scope="overview", language="zh"))
        self.assertIsNotNone(
            store.latest_dashboard(marketplace="US", scope="overview", language="en"))


if __name__ == "__main__":
    unittest.main()
