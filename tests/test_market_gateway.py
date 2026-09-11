"""The metered-call gateway: wallets, dedupe, field pruning, and the pytest backstop.

Every test that wants a (faked) vendor call must opt in with
``MARKETING_AGENT_TEST_LIVE_VENDOR=1`` — that is the same switch a human would use,
and ``test_pytest_is_refused_even_with_a_key`` proves what happens without it.
"""
from __future__ import annotations

import json
import os
import unittest
from unittest import mock

from marketing_agent.tools.mcp_client import McpToolError, McpUnavailable
from server import db
from server.market import fields, gateway, store

_REPLY = json.dumps({"code": "OK", "data": {"items": [{"asin": "B01", "price": 429.0}]}})
_EMPTY = json.dumps({"code": "OK", "data": {"items": []}})


class GatewayTestCase(unittest.TestCase):
    """Shared setup: a configured vendor, a faked transport, and a clean ledger."""

    def setUp(self) -> None:
        db.reset_for_tests()
        gateway.clear_cache()
        self._env = {k: os.environ.get(k) for k in
                     ("MARKETING_AGENT_TEST_LIVE_VENDOR", "SELLERSPRITE_SECRET_KEY")}
        os.environ["MARKETING_AGENT_TEST_LIVE_VENDOR"] = "1"
        os.environ["SELLERSPRITE_SECRET_KEY"] = "test-key"
        self._limits = dict(gateway.DAILY_LIMITS)

    def tearDown(self) -> None:
        gateway.DAILY_LIMITS.clear()
        gateway.DAILY_LIMITS.update(self._limits)
        for key, value in self._env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        gateway.clear_cache()
        db.reset_for_tests()


class PytestGuardTests(GatewayTestCase):
    def test_pytest_is_refused_even_with_a_key(self) -> None:
        """conftest clears the key; this is the backstop for a test that sets it
        back and forgets to fake the transport."""
        os.environ.pop("MARKETING_AGENT_TEST_LIVE_VENDOR", None)
        with mock.patch.object(gateway.sellersprite, "call_tool") as called:
            with self.assertRaises(McpUnavailable) as ctx:
                gateway.call("market_research", {"request": {}})
        called.assert_not_called()
        self.assertIn("MARKETING_AGENT_TEST_LIVE_VENDOR", str(ctx.exception))

    def test_an_unconfigured_vendor_never_reaches_the_transport(self) -> None:
        os.environ["SELLERSPRITE_SECRET_KEY"] = ""
        with mock.patch.object(gateway.sellersprite, "call_tool") as called:
            with self.assertRaises(McpUnavailable):
                gateway.call("market_research", {"request": {}})
        called.assert_not_called()


class BudgetTests(GatewayTestCase):
    def test_a_wallet_stops_at_its_cap(self) -> None:
        gateway.DAILY_LIMITS[gateway.BUCKET_SWEEP] = 45
        with mock.patch.object(gateway.sellersprite, "call_tool", return_value=_REPLY) as vendor:
            for i in range(50):
                try:
                    gateway.call("product_research", {"request": {"page": i}},
                                 purpose="cap test")
                except gateway.BudgetExhausted:
                    break
        self.assertEqual(vendor.call_count, 45)
        self.assertEqual(store.calls_used("US", gateway.run_date(), "sweep"), 45)

    def test_wallets_do_not_compete(self) -> None:
        """A burst of on-demand research must never eat the scheduled snapshot."""
        gateway.DAILY_LIMITS[gateway.BUCKET_SWEEP] = 2
        gateway.DAILY_LIMITS[gateway.BUCKET_DEEPDIVE] = 3
        with mock.patch.object(gateway.sellersprite, "call_tool", return_value=_REPLY):
            for i in range(5):
                try:
                    gateway.call("product_research", {"request": {"p": i}},
                                 bucket=gateway.BUCKET_DEEPDIVE)
                except gateway.BudgetExhausted:
                    pass
            gateway.call("product_research", {"request": {"sweep": 1}})
        self.assertEqual(store.calls_used("US", gateway.run_date(), "deepdive"), 3)
        self.assertEqual(store.calls_used("US", gateway.run_date(), "sweep"), 1)

    def test_a_zero_limit_wallet_refuses_immediately(self) -> None:
        """A misconfigured env must not be able to produce an unbounded sweep."""
        gateway.DAILY_LIMITS[gateway.BUCKET_SWEEP] = 0
        with mock.patch.object(gateway.sellersprite, "call_tool") as vendor:
            with self.assertRaises(gateway.BudgetExhausted):
                gateway.call("product_research", {"request": {}})
        vendor.assert_not_called()

    def test_budget_status_reports_every_wallet(self) -> None:
        with mock.patch.object(gateway.sellersprite, "call_tool", return_value=_REPLY):
            gateway.call("product_research", {"request": {}})
        status = gateway.budget_status()
        self.assertEqual(status["total_used"], 1)
        self.assertEqual(status["wallets"]["sweep"]["used"], 1)
        self.assertEqual(status["wallets"]["deepdive"]["used"], 0)


class CachingTests(GatewayTestCase):
    def test_identical_arguments_are_billed_once(self) -> None:
        with mock.patch.object(gateway.sellersprite, "call_tool", return_value=_REPLY) as vendor:
            first = gateway.call("product_research", {"request": {"nodeIdPath": "1:2"}})
            second = gateway.call("product_research", {"request": {"nodeIdPath": "1:2"}})
        self.assertEqual(vendor.call_count, 1)
        self.assertTrue(first.billable)
        self.assertFalse(second.billable)
        self.assertEqual(second.status, "cached")
        self.assertEqual(second.payload, first.payload)
        self.assertEqual(store.calls_used("US", gateway.run_date()), 1)

    def test_argument_order_does_not_defeat_the_cache(self) -> None:
        with mock.patch.object(gateway.sellersprite, "call_tool", return_value=_REPLY) as vendor:
            gateway.call("product_research", {"request": {"a": 1, "b": 2}})
            gateway.call("product_research", {"request": {"b": 2, "a": 1}})
        self.assertEqual(vendor.call_count, 1)

    def test_an_empty_reply_is_not_cached(self) -> None:
        """An empty month may fill in later; caching it would hide that."""
        with mock.patch.object(gateway.sellersprite, "call_tool", return_value=_EMPTY) as vendor:
            gateway.call("product_research", {"request": {}}, allow_drift_retry=False)
            gateway.call("product_research", {"request": {}}, allow_drift_retry=False)
        self.assertEqual(vendor.call_count, 2)


class FieldPruningTests(GatewayTestCase):
    def test_return_fields_are_injected_into_the_nested_request(self) -> None:
        with mock.patch.object(gateway.sellersprite, "call_tool", return_value=_REPLY) as vendor:
            gateway.call("product_research", {"request": {"nodeIdPath": "1:2"}})
        sent = vendor.call_args.args[1]["request"]
        self.assertIn("returnFields", sent)
        self.assertIn("asin", sent["returnFields"].split(","))
        self.assertEqual(sent["nodeIdPath"], "1:2")

    def test_return_fields_are_injected_into_flat_arguments(self) -> None:
        with mock.patch.object(gateway.sellersprite, "call_tool", return_value=_REPLY) as vendor:
            gateway.call("review", {"marketplace": "US", "asin": "B01"})
        sent = vendor.call_args.args[1]
        self.assertIn("content", sent["returnFields"].split(","))

    def test_a_caller_supplied_field_list_is_respected(self) -> None:
        with mock.patch.object(gateway.sellersprite, "call_tool", return_value=_REPLY) as vendor:
            gateway.call("product_research", {"request": {"returnFields": "asin"}})
        self.assertEqual(vendor.call_args.args[1]["request"]["returnFields"], "asin")

    def test_tools_marked_unpruned_are_sent_bare(self) -> None:
        """Nested replies are pruned at extraction; naming a container would break them."""
        with mock.patch.object(gateway.sellersprite, "call_tool", return_value=_REPLY) as vendor:
            gateway.call("asin_prediction", {"marketplace": "US", "asin": "B01"})
        self.assertNotIn("returnFields", vendor.call_args.args[1])
        self.assertIn("asin_prediction", fields.UNPRUNED)

    def test_an_empty_pruned_reply_triggers_one_bare_retry(self) -> None:
        """A vendor rename would otherwise read as a month of empty markets."""
        payloads = [_EMPTY, _REPLY]
        with mock.patch.object(gateway.sellersprite, "call_tool",
                               side_effect=payloads) as vendor:
            reply = gateway.call("product_research", {"request": {"nodeIdPath": "1:2"}})
        self.assertEqual(vendor.call_count, 2)
        self.assertNotIn("returnFields", vendor.call_args.args[1]["request"])
        self.assertTrue(reply.ok)
        statuses = [c["status"] for c in store.call_log("US", gateway.run_date())]
        self.assertIn("field_drift", statuses)

    def test_the_drift_retry_is_capped_per_day(self) -> None:
        with mock.patch.object(gateway.sellersprite, "call_tool", return_value=_EMPTY) as vendor:
            for i in range(6):
                gateway.call("product_research", {"request": {"page": i}})
        # Three pruned calls got a retry; the rest were left pruned.
        drifts = [c for c in store.call_log("US", gateway.run_date())
                  if c["status"] == "field_drift"]
        self.assertEqual(len(drifts), gateway.MAX_FIELD_DRIFT_RETRIES)
        self.assertEqual(vendor.call_count, 6 + gateway.MAX_FIELD_DRIFT_RETRIES)


class FailureTests(GatewayTestCase):
    def test_a_vendor_rejection_is_an_answer_and_is_still_billed(self) -> None:
        with mock.patch.object(gateway.sellersprite, "call_tool",
                               side_effect=McpToolError("no permission for this endpoint")):
            reply = gateway.call("keyword_miner", {"request": {}})
        self.assertEqual(reply.status, "rejected")
        self.assertTrue(reply.billable)
        self.assertIn("no permission", reply.detail)
        self.assertEqual(store.calls_used("US", gateway.run_date()), 1)

    def test_transport_failure_is_raised_and_not_billed(self) -> None:
        with mock.patch.object(gateway.sellersprite, "call_tool",
                               side_effect=McpUnavailable("connection reset")):
            with self.assertRaises(McpUnavailable):
                gateway.call("market_research", {"request": {}})
        self.assertEqual(store.calls_used("US", gateway.run_date()), 0)
        self.assertEqual(store.call_log("US", gateway.run_date())[0]["status"], "unavailable")

    def test_an_unexpected_client_error_is_contained(self) -> None:
        with mock.patch.object(gateway.sellersprite, "call_tool",
                               side_effect=RuntimeError("boom")):
            reply = gateway.call("market_research", {"request": {}})
        self.assertEqual(reply.status, "error")
        self.assertFalse(reply.ok)


class ClockTests(GatewayTestCase):
    def test_the_period_follows_the_marketplace_clock_not_the_server(self) -> None:
        """The old sweep used the server's local month, so a UTC or China-hosted box
        asked for a month the US marketplace had not entered."""
        self.assertEqual(len(gateway.current_period()), 6)
        self.assertEqual(gateway.sweep_now().tzinfo.key, gateway.SWEEP_TZ)

    def test_previous_period_rolls_the_year(self) -> None:
        from datetime import datetime
        from zoneinfo import ZoneInfo
        january = datetime(2026, 1, 4, tzinfo=ZoneInfo("America/Los_Angeles"))
        self.assertEqual(gateway.previous_period(january), "202512")
        self.assertEqual(gateway.current_period(january), "202601")

    def test_an_unknown_timezone_degrades_to_utc(self) -> None:
        self.assertIsNotNone(gateway.sweep_now("Not/AZone"))


if __name__ == "__main__":
    unittest.main()
