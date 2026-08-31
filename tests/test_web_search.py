"""Tests for the pluggable web-search providers."""
from __future__ import annotations

import unittest
from unittest import mock

from marketing_agent.tools import web_search


class ProviderSelectionTests(unittest.TestCase):
    def test_no_key_means_unavailable(self) -> None:
        with mock.patch.dict("os.environ", {k: "" for k in web_search._PROVIDER_KEYS.values()}, clear=False):
            with mock.patch.dict("os.environ", {"MARKETING_AGENT_SEARCH_PROVIDER": ""}, clear=False):
                self.assertFalse(web_search.is_available())
                self.assertIn("DeepSeek has no built-in web search", web_search.unavailable_reason())

    def test_gemini_key_alone_enables_search(self) -> None:
        env = {k: "" for k in web_search._PROVIDER_KEYS.values()}
        env["GEMINI_API_KEY"] = "gem-key"
        env["MARKETING_AGENT_SEARCH_PROVIDER"] = ""
        with mock.patch.dict("os.environ", env, clear=False):
            self.assertEqual(web_search.active_provider(), ("gemini", "gem-key"))

    def test_dedicated_vendor_wins_over_gemini(self) -> None:
        # Gemini grounding carries no publication date, so a real search API
        # should take priority when both are configured.
        env = {k: "" for k in web_search._PROVIDER_KEYS.values()}
        env["GEMINI_API_KEY"] = "gem-key"
        env["TAVILY_API_KEY"] = "tvly-key"
        env["MARKETING_AGENT_SEARCH_PROVIDER"] = ""
        with mock.patch.dict("os.environ", env, clear=False):
            self.assertEqual(web_search.active_provider(), ("tavily", "tvly-key"))

    def test_explicit_pin_overrides_order(self) -> None:
        env = {k: "" for k in web_search._PROVIDER_KEYS.values()}
        env["GEMINI_API_KEY"] = "gem-key"
        env["TAVILY_API_KEY"] = "tvly-key"
        env["MARKETING_AGENT_SEARCH_PROVIDER"] = "gemini"
        with mock.patch.dict("os.environ", env, clear=False):
            self.assertEqual(web_search.active_provider(), ("gemini", "gem-key"))


_GROUNDED_RESPONSE = {
    "candidates": [
        {
            "groundingMetadata": {
                "groundingChunks": [
                    {"web": {"uri": "https://vertexaisearch.cloud.google.com/grounding-api-redirect/AAA", "title": "cbp.gov"}},
                    {"web": {"uri": "https://vertexaisearch.cloud.google.com/grounding-api-redirect/BBB", "title": "furnituretoday.com"}},
                    # Duplicate of the first once resolved — must be dropped.
                    {"web": {"uri": "https://vertexaisearch.cloud.google.com/grounding-api-redirect/AAA", "title": "cbp.gov"}},
                ],
                "groundingSupports": [
                    {"segment": {"text": "Duties rose in April 2026."}, "groundingChunkIndices": [0]},
                    {"segment": {"text": "Retail demand stayed soft."}, "groundingChunkIndices": [1]},
                ],
            }
        }
    ]
}

_RESOLVED = {
    "https://vertexaisearch.cloud.google.com/grounding-api-redirect/AAA": "https://www.cbp.gov/trade/duty",
    "https://vertexaisearch.cloud.google.com/grounding-api-redirect/BBB": "https://www.furnituretoday.com/news/x",
}


class _FakeClient:
    """Stands in for httpx.Client during redirect resolution."""

    def __init__(self, mapping, fail_for=()):
        self._mapping = mapping
        self._fail_for = set(fail_for)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def head(self, url):
        import httpx

        if url in self._fail_for:
            raise httpx.ConnectError("boom")
        return mock.Mock(url=self._mapping[url])


class GeminiProviderTests(unittest.TestCase):
    def _run(self, client, limit=6):
        with mock.patch.object(web_search, "_post", return_value=_GROUNDED_RESPONSE), \
                mock.patch.object(web_search.httpx, "Client", return_value=client):
            return web_search._gemini("gem-key", "furniture tariffs", limit)

    def test_redirects_resolve_to_publisher_urls(self) -> None:
        # Source-tier scoring keys off the domain, so an unresolved Vertex
        # redirect would make every citation score as the same unknown host.
        results = self._run(_FakeClient(_RESOLVED))
        self.assertEqual(
            [r.url for r in results],
            ["https://www.cbp.gov/trade/duty", "https://www.furnituretoday.com/news/x"],
        )

    def test_snippets_come_from_the_citing_answer_segments(self) -> None:
        results = self._run(_FakeClient(_RESOLVED))
        self.assertEqual(results[0].snippet, "Duties rose in April 2026.")
        self.assertEqual(results[1].snippet, "Retail demand stayed soft.")

    def test_duplicate_sources_are_collapsed(self) -> None:
        results = self._run(_FakeClient(_RESOLVED))
        self.assertEqual(len(results), 2)

    def test_unresolvable_redirect_keeps_the_redirect_url(self) -> None:
        failing = _FakeClient(
            _RESOLVED,
            fail_for=["https://vertexaisearch.cloud.google.com/grounding-api-redirect/AAA"],
        )
        results = self._run(failing)
        # Still clickable, just scores as an unknown domain — better than dropping it.
        self.assertTrue(results[0].url.endswith("/AAA"))
        self.assertEqual(len(results), 2)

    def test_limit_is_honored(self) -> None:
        results = self._run(_FakeClient(_RESOLVED), limit=1)
        self.assertEqual(len(results), 1)

    def test_ungrounded_answer_returns_nothing(self) -> None:
        # If the model answered from memory without searching, those claims are
        # unsourced and must not be presented as search results.
        with mock.patch.object(web_search, "_post", return_value={"candidates": [{}]}):
            self.assertEqual(web_search._gemini("gem-key", "q", 5), [])


class GeminiRetryTests(unittest.TestCase):
    """Google returns 503 on transient capacity spikes; a bad key must not retry."""

    def test_transient_503_is_retried_once(self) -> None:
        transient = web_search.SearchUnavailable("busy", status_code=503)
        calls = {"n": 0}

        def flaky(*args, **kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                raise transient
            return {"candidates": [{}]}

        with mock.patch.object(web_search, "_post", side_effect=flaky),                 mock.patch.object(web_search.time, "sleep") as sleep:
            result = web_search._post_with_retry("http://x", {}, "k")

        self.assertEqual(calls["n"], 2)
        self.assertEqual(result, {"candidates": [{}]})
        sleep.assert_called_once()

    def test_auth_failure_is_not_retried(self) -> None:
        denied = web_search.SearchUnavailable("bad key", status_code=403)
        with mock.patch.object(web_search, "_post", side_effect=denied) as post:
            with self.assertRaises(web_search.SearchUnavailable):
                web_search._post_with_retry("http://x", {}, "k")
        self.assertEqual(post.call_count, 1)

    def test_persistent_503_surfaces_the_error(self) -> None:
        busy = web_search.SearchUnavailable("busy", status_code=503)
        with mock.patch.object(web_search, "_post", side_effect=busy) as post,                 mock.patch.object(web_search.time, "sleep"):
            with self.assertRaises(web_search.SearchUnavailable) as ctx:
                web_search._post_with_retry("http://x", {}, "k")
        self.assertEqual(post.call_count, web_search._GEMINI_ATTEMPTS)
        self.assertEqual(ctx.exception.status_code, 503)

    def test_handler_degrades_instead_of_raising(self) -> None:
        # A failed search must come back to the model as text, not blow up the turn.
        with mock.patch.object(
            web_search, "search", side_effect=web_search.SearchUnavailable("busy", status_code=503)
        ):
            out = web_search.handle_web_search({"query": "furniture tariffs"})
        self.assertIn("web search is unavailable", out)


if __name__ == "__main__":
    unittest.main()
