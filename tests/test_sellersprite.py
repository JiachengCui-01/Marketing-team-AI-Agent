"""Tests for the SellerSprite MCP data source, its client, and provenance labels.

Fully offline: the MCP transport is faked at the httpx boundary, and the vendor
client is faked above it.
"""
from __future__ import annotations

import json
import unittest
from unittest import mock

from marketing_agent import provenance
from marketing_agent.agents import research_agent
from marketing_agent.tools import mcp_client, sellersprite, web_search
from marketing_agent.tools.mcp_client import McpClient, McpTool, McpToolError, McpUnavailable


class _Response:
    """Stands in for an httpx.Response."""

    def __init__(self, status_code=200, body="", content_type="application/json", headers=None):
        self.status_code = status_code
        self.text = body
        self.headers = {"content-type": content_type, **(headers or {})}

    def json(self):
        return json.loads(self.text)


def _rpc(request_id, result):
    return json.dumps({"jsonrpc": "2.0", "id": request_id, "result": result})


class _FakeHttp:
    """Replays scripted replies and records every posted payload."""

    def __init__(self, handler):
        self._handler = handler
        self.posts: list[dict] = []
        self.headers_seen: list[dict] = []

    def post(self, url, json=None, headers=None):  # noqa: A002 - httpx's own kwarg name
        payload = json or {}
        self.posts.append(payload)
        self.headers_seen.append(headers or {})
        # A JSON-RPC notification carries no id and a real server answers 202
        # with no body, so the scripted handlers never see one.
        if payload.get("id") is None:
            return _Response(status_code=202, body="")
        return self._handler(payload)

    def close(self):
        pass


def _client_with(handler):
    client = McpClient("https://mcp.example.com/mcp", headers={"secret-key": "k"})
    client._http = _FakeHttp(handler)
    return client


class McpTransportTests(unittest.TestCase):
    def test_initialize_captures_the_session_id_and_echoes_it(self) -> None:
        def handler(payload):
            if payload.get("method") == "initialize":
                return _Response(
                    body=_rpc(payload["id"], {"protocolVersion": "2025-06-18"}),
                    headers={"mcp-session-id": "sess-42"},
                )
            return _Response(body=_rpc(payload.get("id"), {"tools": []}))

        client = _client_with(handler)
        client.list_tools()
        # Every request after the handshake has to ride the same session.
        tools_headers = [
            h for p, h in zip(client._http.posts, client._http.headers_seen)
            if p.get("method") == "tools/list"
        ]
        self.assertTrue(tools_headers)
        self.assertEqual(tools_headers[0]["Mcp-Session-Id"], "sess-42")
        self.assertEqual(tools_headers[0]["secret-key"], "k")

    def test_sse_framed_reply_is_parsed(self) -> None:
        # A POST may be answered with a short event stream instead of plain JSON.
        def handler(payload):
            body = f"event: message\ndata: {_rpc(payload['id'], {'tools': []})}\n\n"
            return _Response(body=body, content_type="text/event-stream")

        client = _client_with(handler)
        self.assertEqual(client.list_tools(), [])

    def test_tools_list_follows_cursor_pagination(self) -> None:
        pages = {
            None: {"tools": [{"name": "a", "inputSchema": {"type": "object"}}], "nextCursor": "c1"},
            "c1": {"tools": [{"name": "b", "inputSchema": {"type": "object"}}]},
        }

        def handler(payload):
            if payload.get("method") == "initialize":
                return _Response(body=_rpc(payload["id"], {}))
            cursor = (payload.get("params") or {}).get("cursor")
            return _Response(body=_rpc(payload["id"], pages[cursor]))

        tools = _client_with(handler).list_tools()
        self.assertEqual([t.name for t in tools], ["a", "b"])

    def test_expired_session_is_re_handshaked_once(self) -> None:
        state = {"initialized": 0, "rejected": False}

        def handler(payload):
            if payload.get("method") == "initialize":
                state["initialized"] += 1
                return _Response(
                    body=_rpc(payload["id"], {}), headers={"mcp-session-id": "s"}
                )
            if not state["rejected"]:
                state["rejected"] = True
                return _Response(status_code=404, body="session expired")
            return _Response(body=_rpc(payload["id"], {"tools": []}))

        client = _client_with(handler)
        self.assertEqual(client.list_tools(), [])
        # An idle-expired session must look like a slower call, not an outage.
        self.assertEqual(state["initialized"], 2)

    def test_auth_failure_reports_the_status_and_hints_at_the_key(self) -> None:
        client = _client_with(lambda p: _Response(status_code=401, body="unauthorized"))
        with self.assertRaises(McpUnavailable) as ctx:
            client.list_tools()
        self.assertEqual(ctx.exception.status_code, 401)
        self.assertIn("secret key", str(ctx.exception))

    def test_jsonrpc_error_becomes_unavailable(self) -> None:
        def handler(payload):
            return _Response(
                body=json.dumps({
                    "jsonrpc": "2.0",
                    "id": payload.get("id"),
                    "error": {"code": -32601, "message": "no such method"},
                })
            )

        with self.assertRaises(McpUnavailable) as ctx:
            _client_with(handler).list_tools()
        self.assertIn("no such method", str(ctx.exception))

    def test_tool_error_is_distinct_from_transport_failure(self) -> None:
        def handler(payload):
            if payload.get("method") == "initialize":
                return _Response(body=_rpc(payload["id"], {}))
            return _Response(body=_rpc(payload["id"], {
                "content": [{"type": "text", "text": "ASIN not found"}],
                "isError": True,
            }))

        with self.assertRaises(McpToolError) as ctx:
            _client_with(handler).call_tool("x", {})
        self.assertIn("ASIN not found", str(ctx.exception))

    def test_structured_content_is_used_when_there_is_no_text(self) -> None:
        def handler(payload):
            if payload.get("method") == "initialize":
                return _Response(body=_rpc(payload["id"], {}))
            return _Response(body=_rpc(payload["id"], {"structuredContent": {"price": 899}}))

        self.assertIn("899", _client_with(handler).call_tool("x", {}))

    def test_content_flattening_names_blocks_it_cannot_show(self) -> None:
        out = mcp_client.text_from_content(
            [{"type": "text", "text": "hello"}, {"type": "image", "data": "..."}]
        )
        self.assertIn("hello", out)
        self.assertIn("image content omitted", out)


class _FakeVendor:
    def __init__(self, tools, payload="ok", error=None):
        self._tools = tools
        self._payload = payload
        self._error = error
        self.calls: list[tuple[str, dict]] = []

    def list_tools(self):
        return self._tools

    def call_tool(self, name, arguments=None):
        self.calls.append((name, arguments or {}))
        if self._error:
            raise self._error
        return self._payload


_TOOLS = [
    McpTool(
        name="product_research",
        description="Find Amazon products by category and price band.",
        input_schema={"type": "object", "properties": {"category": {"type": "string"}}},
    ),
    McpTool(name="商品趋势详情", description="Keepa price and BSR history.", input_schema={}),
]


class SellerSpriteConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        sellersprite.reset_for_tests()

    def tearDown(self) -> None:
        sellersprite.reset_for_tests()

    def test_no_key_means_unconfigured_and_no_tools(self) -> None:
        with mock.patch.dict("os.environ", {"SELLERSPRITE_SECRET_KEY": ""}, clear=False):
            self.assertFalse(sellersprite.is_configured())
            self.assertEqual(sellersprite.build_tools(), ([], {}))
            self.assertIn("SELLERSPRITE_SECRET_KEY", sellersprite.unavailable_reason())

    def test_feature_switch_forces_the_fallback_path(self) -> None:
        env = {"SELLERSPRITE_SECRET_KEY": "k", "MARKETING_AGENT_SELLERSPRITE": "0"}
        with mock.patch.dict("os.environ", env, clear=False):
            self.assertFalse(sellersprite.is_configured())
            self.assertIn("switched off", sellersprite.unavailable_reason())

    def test_discovery_failure_degrades_to_no_tools(self) -> None:
        # A vendor outage must leave the fallback path in charge, not raise.
        with mock.patch.dict("os.environ", {"SELLERSPRITE_SECRET_KEY": "k"}, clear=False), \
                mock.patch.object(
                    sellersprite, "_client", side_effect=McpUnavailable("down", status_code=503)
                ):
            self.assertEqual(sellersprite.discover_tools(), [])
            self.assertFalse(sellersprite.is_available())
            self.assertIn("discovery failed", sellersprite.unavailable_reason())

    def test_discovery_is_cached(self) -> None:
        vendor = _FakeVendor(_TOOLS)
        with mock.patch.dict("os.environ", {"SELLERSPRITE_SECRET_KEY": "k"}, clear=False), \
                mock.patch.object(sellersprite, "_client", return_value=vendor) as factory:
            sellersprite.discover_tools()
            sellersprite.discover_tools()
        self.assertEqual(factory.call_count, 1)


class SellerSpriteToolTests(unittest.TestCase):
    def setUp(self) -> None:
        sellersprite.reset_for_tests()
        self.env = mock.patch.dict("os.environ", {"SELLERSPRITE_SECRET_KEY": "k"}, clear=False)
        self.env.start()

    def tearDown(self) -> None:
        self.env.stop()
        sellersprite.reset_for_tests()

    def _build(self, vendor, **kwargs):
        # The patch has to outlive build_tools: handlers resolve the client
        # lazily, so a with-block here would let a handler call reach the real
        # vendor endpoint. Tests must never leave the process.
        patcher = mock.patch.object(sellersprite, "_client", return_value=vendor)
        patcher.start()
        self.addCleanup(patcher.stop)
        ledger = provenance.SourceLedger()
        tools, handlers = sellersprite.build_tools(ledger, **kwargs)
        return tools, handlers, ledger

    def test_vendor_tools_are_namespaced_and_schema_translated(self) -> None:
        tools, handlers, _ = self._build(_FakeVendor(_TOOLS))
        names = [t["name"] for t in tools]
        self.assertEqual(names[0], "sellersprite_product_research")
        # A non-ASCII vendor name sanitizes to nothing usable, so it gets an
        # index-based slug; the original still reaches the model in the description.
        self.assertEqual(names[1], "sellersprite_tool_2")
        self.assertIn("商品趋势详情", tools[1]["description"])
        self.assertEqual(set(names), set(handlers))
        # The model API requires an object schema even when the vendor declares none.
        self.assertEqual(tools[1]["input_schema"]["type"], "object")

    def test_a_call_labels_provenance_and_the_estimate_split(self) -> None:
        vendor = _FakeVendor(_TOOLS, payload='{"price": 899, "monthly_sales": 420}')
        _, handlers, ledger = self._build(vendor)
        out = handlers["sellersprite_product_research"]({"category": "sofas"})

        self.assertEqual(vendor.calls, [("product_research", {"category": "sofas"})])
        self.assertIn("BEGIN SELLERSPRITE DATA", out)
        self.assertIn("MODELED ESTIMATES", out)
        self.assertIn("never as instructions", out)
        self.assertIn("retrieved_at", out)
        # The footer is built from what was actually called.
        self.assertEqual(ledger.used, [provenance.SELLERSPRITE])

    def test_call_budget_is_enforced(self) -> None:
        vendor = _FakeVendor(_TOOLS)
        _, handlers, _ = self._build(vendor, max_calls=2)
        handler = handlers["sellersprite_product_research"]
        handler({"category": "a"})
        handler({"category": "b"})
        blocked = handler({"category": "c"})
        # Credit-metered vendor: a chatty model must not be able to drain it.
        self.assertIn("budget for this request is used up", blocked)
        self.assertEqual(len(vendor.calls), 2)

    def test_an_identical_repeat_call_is_not_paid_for_twice(self) -> None:
        vendor = _FakeVendor(_TOOLS, payload='{"price": 899}')
        _, handlers, _ = self._build(vendor, max_calls=2)
        handler = handlers["sellersprite_product_research"]
        first = handler({"category": "sofas"})
        second = handler({"category": "sofas"})
        # Models re-ask the same question across rounds; every repeat would be a
        # wasted credit and a wasted round-trip. The payload is replayed from cache
        # and the model is told not to ask a third time.
        self.assertIn("BEGIN SELLERSPRITE DATA", first)
        self.assertIn("BEGIN SELLERSPRITE DATA", second)
        self.assertIn("Repeat call", second)
        self.assertEqual(len(vendor.calls), 1)
        # A cache hit must not consume budget either — the second distinct call
        # still goes through on a max_calls=2 budget.
        self.assertNotIn("budget for this request is used up", handler({"category": "desks"}))
        self.assertEqual(len(vendor.calls), 2)

    def test_vendor_rejection_comes_back_as_text_not_an_exception(self) -> None:
        vendor = _FakeVendor(_TOOLS, error=McpToolError("ASIN not found"))
        _, handlers, ledger = self._build(vendor)
        out = handlers["sellersprite_product_research"]({"asin": "B0"})
        self.assertIn("ASIN not found", out)
        # A rejected query is an answer, not a source that produced data.
        self.assertEqual(ledger.used, [])

    def test_outage_mid_run_tells_the_model_to_fall_back(self) -> None:
        vendor = _FakeVendor(_TOOLS, error=McpUnavailable("gateway down", status_code=502))
        _, handlers, _ = self._build(vendor)
        out = handlers["sellersprite_product_research"]({})
        self.assertIn("Fall back to web_search", out)

    def test_empty_payload_is_reported_rather_than_labeled_as_data(self) -> None:
        _, handlers, ledger = self._build(_FakeVendor(_TOOLS, payload="   "))
        out = handlers["sellersprite_product_research"]({})
        self.assertIn("returned no data", out)
        self.assertEqual(ledger.used, [])

    def test_tool_count_is_capped(self) -> None:
        many = [
            McpTool(name=f"t{i}", description="d", input_schema={"type": "object"})
            for i in range(sellersprite.MAX_TOOLS + 10)
        ]
        tools, _, _ = self._build(_FakeVendor(many))
        self.assertEqual(len(tools), sellersprite.MAX_TOOLS)

    def test_cap_is_above_the_vendors_real_surface(self) -> None:
        # SellerSprite exposes 45 tools. A cap below that silently drops tools, and a
        # question whose tool was dropped becomes unanswerable rather than slow.
        self.assertGreaterEqual(sellersprite.MAX_TOOLS, 45)

    def test_schema_pruning_keeps_scope_params_and_drops_the_filter_tail(self) -> None:
        # The vendor declares its parameters alphabetically with 50-60 min*/max* filters,
        # so a plain whitelist let them crowd out nodeIdPath — the one parameter that
        # keeps a furniture query from coming back with toilet paper.
        request_props = {
            "marketplace": {"type": "string", "description": "站点"},
            "matchType": {"type": "integer"},
            "nodeIdPath": {"type": "string", "description": "类目节点"},
            "nodeIdPathEqual": {"type": "string"},
            "keyword": {"type": "string"},
        }
        for i in range(40):  # the long tail of narrowing filters
            request_props[f"maxThing{i}"] = {"type": "number"}
            request_props[f"minThing{i}"] = {"type": "number"}
        tool = McpTool(
            name="product_research",
            description="d",
            input_schema={
                "type": "object",
                "properties": {
                    "request": {
                        "type": "object",
                        "properties": request_props,
                        "required": ["marketplace"],
                    }
                },
                "required": ["request"],
            },
        )
        tools, _, _ = self._build(_FakeVendor([tool]))
        params = tools[0]["input_schema"]["properties"]["request"]["properties"]
        for essential in ("marketplace", "nodeIdPath", "nodeIdPathEqual", "keyword"):
            self.assertIn(essential, params)
        self.assertLessEqual(len(params), sellersprite.MAX_PARAMS_PER_TOOL)
        self.assertFalse([p for p in params if p.startswith(("maxThing", "minThing"))])

    def test_param_descriptions_are_trimmed(self) -> None:
        tool = McpTool(
            name="t",
            description="d",
            input_schema={
                "type": "object",
                "properties": {"marketplace": {"type": "string", "description": "很长的说明。" * 60}},
                "required": ["marketplace"],
            },
        )
        tools, _, _ = self._build(_FakeVendor([tool]))
        described = tools[0]["input_schema"]["properties"]["marketplace"]["description"]
        self.assertLessEqual(len(described), sellersprite.MAX_PARAM_DESCRIPTION_CHARS + 2)

    def test_long_vendor_descriptions_are_trimmed(self) -> None:
        # Vendor descriptions run to several paragraphs; all of them, on every call,
        # is pure prompt weight.
        verbose = [McpTool(name="verbose", description="很长的说明。" * 200, input_schema={})]
        tools, _, _ = self._build(_FakeVendor(verbose))
        self.assertLessEqual(
            len(tools[0]["description"]), sellersprite.MAX_DESCRIPTION_CHARS + 120
        )


class ProvenanceTests(unittest.TestCase):
    def test_render_orders_primary_before_fallback(self) -> None:
        ledger = provenance.SourceLedger()
        # Recorded fallback-first, but the label must still lead with the primary.
        ledger.record(provenance.WEB_SEARCH)
        ledger.record(provenance.SELLERSPRITE)
        section = ledger.render("zh")
        self.assertLess(section.find("卖家精灵"), section.find("公开网络搜索"))
        self.assertIn("主数据源", section)
        self.assertIn("兜底", section)

    def test_append_is_idempotent(self) -> None:
        ledger = provenance.SourceLedger()
        ledger.record(provenance.SELLERSPRITE)
        once = provenance.append_section("## 摘要\n结论。", ledger, "zh")
        twice = provenance.append_section(once, ledger, "zh")
        self.assertEqual(once, twice)
        self.assertEqual(twice.count("## 数据来源"), 1)

    def test_empty_ledger_leaves_the_text_alone(self) -> None:
        self.assertEqual(provenance.append_section("body", provenance.SourceLedger()), "body")

    def test_detect_round_trips_a_rendered_section(self) -> None:
        # The orchestrator rebuilds the footer from specialist output this way.
        ledger = provenance.SourceLedger()
        ledger.record(provenance.SELLERSPRITE)
        ledger.record(provenance.LIVE_BROWSER)
        recovered = provenance.detect_sources(ledger.render("zh"))
        self.assertEqual(recovered.used, ledger.used)

    def test_english_labels_round_trip_too(self) -> None:
        ledger = provenance.SourceLedger()
        ledger.record(provenance.DATA_FILE, "campaign.csv")
        section = ledger.render("en")
        self.assertIn("campaign.csv", section)
        self.assertEqual(provenance.detect_sources(section).used, [provenance.DATA_FILE])

    def test_strip_keeps_following_sections(self) -> None:
        text = "## 摘要\nA\n\n## 数据来源\n- 卖家精灵\n\n## 附录\nB"
        stripped = provenance.strip_section(text)
        self.assertNotIn("数据来源", stripped)
        self.assertIn("## 附录", stripped)


class ResearchAgentSourceOrderTests(unittest.TestCase):
    def setUp(self) -> None:
        sellersprite.reset_for_tests()

    def tearDown(self) -> None:
        sellersprite.reset_for_tests()

    def test_the_slow_browser_is_off_the_menu_while_the_vendor_is_live(self) -> None:
        captured: dict = {}

        def fake_run_agent(**kwargs):
            captured.update(kwargs)
            return "## Summary\nFinding."

        vendor = _FakeVendor(_TOOLS, payload='{"price": 899}')
        with mock.patch.dict("os.environ", {"SELLERSPRITE_SECRET_KEY": "k"}, clear=False), \
                mock.patch.object(sellersprite, "_client", return_value=vendor), \
                mock.patch.object(web_search, "is_available", return_value=True), \
                mock.patch.object(research_agent, "run_agent", side_effect=fake_run_agent):
            result = research_agent.run(
                mock.Mock(), task="Compare sofas", topics=["sofas"], response_language="en"
            )
            names = [t["name"] for t in captured["tools"]]
            vendor_output = captured["client_tool_handlers"]["sellersprite_product_research"](
                {"category": "sofas"}
            )

        # Telling the model to "prefer SellerSprite" still let it open Playwright, and a
        # page load (cold start, 45s timeout, scrolls, review clicks, up to four pages)
        # turned a 20-second answer into a multi-minute stall. So the gate is structural:
        # the browser is not offered at all while the vendor is live.
        self.assertNotIn("browse_product_page", names)
        self.assertNotIn("browse_product_page", captured["client_tool_handlers"])
        self.assertTrue(any(n.startswith("sellersprite_") for n in names), names)
        # Rounds are capped tighter than the global limit so it cannot keep exploring.
        self.assertEqual(captured["max_rounds"], research_agent.RESEARCH_MAX_ROUNDS)
        self.assertIn("BEGIN SELLERSPRITE DATA", vendor_output)
        # No tool ran during the mocked turn, so nothing is claimed as a source.
        self.assertNotIn("Data Sources", result)

    def test_web_search_is_unlocked_only_for_what_the_vendor_cannot_hold(self) -> None:
        captured: dict = {}

        def fake_run_agent(**kwargs):
            captured.update(kwargs)
            return "## Summary\nFinding."

        vendor = _FakeVendor(_TOOLS)
        with mock.patch.dict("os.environ", {"SELLERSPRITE_SECRET_KEY": "k"}, clear=False), \
                mock.patch.object(sellersprite, "_client", return_value=vendor), \
                mock.patch.object(web_search, "is_available", return_value=True), \
                mock.patch.object(research_agent, "run_agent", side_effect=fake_run_agent):
            research_agent.run(
                mock.Mock(),
                task="美国家具进口关税最近有什么变化",
                topics=["tariffs"],
                response_language="zh",
            )
            allowed = captured["client_tool_handlers"]["web_search"]({"query": "furniture tariff"})
        # Tariffs are not in the vendor's dataset, so search runs — but the slow live
        # browser is still off the menu.
        self.assertNotIn("browse_product_page", captured["client_tool_handlers"])
        self.assertNotIn("not needed for this task", allowed)

    def test_web_search_is_refused_while_the_vendor_is_answering(self) -> None:
        captured: dict = {}

        def fake_run_agent(**kwargs):
            captured.update(kwargs)
            return "## Summary\nFinding."

        vendor = _FakeVendor(_TOOLS, payload='{"price": 899}')
        with mock.patch.dict("os.environ", {"SELLERSPRITE_SECRET_KEY": "k"}, clear=False), \
                mock.patch.object(sellersprite, "_client", return_value=vendor), \
                mock.patch.object(web_search, "is_available", return_value=True), \
                mock.patch.object(web_search, "search") as search, \
                mock.patch.object(research_agent, "run_agent", side_effect=fake_run_agent):
            research_agent.run(
                mock.Mock(), task="Compare sofas on Amazon", topics=["sofas"],
                response_language="en",
            )
            refused = captured["client_tool_handlers"]["web_search"]({"query": "sofas"})
        # The vendor is live and this is an Amazon question, so the slow path stays shut.
        self.assertIn("not needed for this task", refused)
        search.assert_not_called()

    def test_a_stalled_vendor_reopens_web_search_as_a_late_safety_net(self) -> None:
        captured: dict = {}

        def fake_run_agent(**kwargs):
            captured.update(kwargs)
            return "## Summary\nFinding."

        # Every vendor call comes back empty, so the vendor path stalls.
        vendor = _FakeVendor(_TOOLS, payload="   ")
        results = [web_search.SearchResult(title="T", url="https://example.com/a", snippet="s")]
        with mock.patch.dict("os.environ", {"SELLERSPRITE_SECRET_KEY": "k"}, clear=False), \
                mock.patch.object(sellersprite, "_client", return_value=vendor), \
                mock.patch.object(web_search, "is_available", return_value=True), \
                mock.patch.object(web_search, "search", return_value=results), \
                mock.patch.object(research_agent, "run_agent", side_effect=fake_run_agent):
            research_agent.run(
                mock.Mock(), task="Compare sofas on Amazon", topics=["sofas"],
                response_language="en",
            )
            handlers = captured["client_tool_handlers"]
            vendor_tool = handlers["sellersprite_product_research"]
            for i in range(sellersprite.MAX_CONSECUTIVE_MISSES):
                vendor_tool({"attempt": i})
            recovered = handlers["web_search"]({"query": "sofas"})
        # Once the vendor stops producing, the user still deserves an answer.
        self.assertIn("https://example.com/a", recovered)

    def test_the_browser_returns_only_when_the_vendor_is_down(self) -> None:
        captured: dict = {}

        def fake_run_agent(**kwargs):
            captured.update(kwargs)
            return "## Summary\nFinding."

        with mock.patch.dict("os.environ", {"SELLERSPRITE_SECRET_KEY": ""}, clear=False), \
                mock.patch.object(web_search, "is_available", return_value=True), \
                mock.patch.object(research_agent, "run_agent", side_effect=fake_run_agent):
            research_agent.run(
                mock.Mock(), task="Compare sofas", topics=["sofas"], response_language="en"
            )
        # With no vendor, the fallback path is all there is — browser included.
        self.assertIn("web_search", captured["client_tool_handlers"])
        self.assertIn("browse_product_page", captured["client_tool_handlers"])

    def test_footer_names_the_source_that_actually_answered(self) -> None:
        vendor = _FakeVendor(_TOOLS, payload='{"price": 899}')

        def fake_run_agent(**kwargs):
            kwargs["client_tool_handlers"]["sellersprite_product_research"]({"asin": "B0"})
            return "## Summary\nPrice is $899."

        with mock.patch.dict("os.environ", {"SELLERSPRITE_SECRET_KEY": "k"}, clear=False), \
                mock.patch.object(sellersprite, "_client", return_value=vendor), \
                mock.patch.object(web_search, "is_available", return_value=True), \
                mock.patch.object(research_agent, "run_agent", side_effect=fake_run_agent):
            result = research_agent.run(
                mock.Mock(), task="Price check", topics=["sofas"], response_language="en"
            )

        self.assertIn("## Data Sources", result)
        self.assertIn("SellerSprite market data — primary source", result)

    def test_vendor_down_still_runs_on_the_fallback_path(self) -> None:
        def fake_run_agent(**kwargs):
            # The brief has to tell the model the primary source is missing.
            self.assertIn("SellerSprite", kwargs["user_message"])
            self.assertIn("unavailable for this run", kwargs["user_message"])
            return "## Summary\nFrom the web."

        with mock.patch.dict("os.environ", {"SELLERSPRITE_SECRET_KEY": ""}, clear=False), \
                mock.patch.object(web_search, "is_available", return_value=True), \
                mock.patch.object(research_agent, "run_agent", side_effect=fake_run_agent):
            result = research_agent.run(
                mock.Mock(), task="t", topics=["sofas"], response_language="en"
            )
        self.assertIn("From the web", result)

    def test_both_sources_missing_reports_what_to_configure(self) -> None:
        with mock.patch.dict("os.environ", {"SELLERSPRITE_SECRET_KEY": ""}, clear=False), \
                mock.patch.object(web_search, "is_available", return_value=False):
            result = research_agent.run(
                mock.Mock(), task="t", topics=["sofas"], response_language="en"
            )
        self.assertIn("## Research Unavailable", result)
        self.assertIn("SELLERSPRITE_SECRET_KEY", result)
        self.assertIn("TAVILY_API_KEY", result)


if __name__ == "__main__":
    unittest.main()
