"""Client-side web search tool for the research agent.

Anthropic served ``web_search`` as a server-side tool; DeepSeek has no
equivalent, so search happens here and the results are handed back to the model
as an ordinary tool result. Everything downstream (inline citations, source-tier
scoring in ``source_scoring``) keeps working because the model still writes the
URLs into its answer.

Providers are pluggable and picked from whichever API key is configured, so the
deployment can use whatever search vendor it already pays for:

===============  ==========================  ==================================
provider          env var                     notes
===============  ==========================  ==================================
tavily            ``TAVILY_API_KEY``          LLM-oriented, returns clean text
serper            ``SERPER_API_KEY``          Google results via serper.dev
brave             ``BRAVE_SEARCH_API_KEY``    Brave Search API
bocha             ``BOCHA_API_KEY``           博查, strongest for Chinese queries
gemini            ``GEMINI_API_KEY``          Google Search grounding; reuses the
                                              image-generation key, so it needs no
                                              extra vendor signup
===============  ==========================  ==================================

Auto-detection walks that table in order, so a dedicated search vendor always
wins over ``gemini`` when both are configured — the dedicated APIs return
publication dates, which Gemini grounding does not (see ``_gemini``). Set
``MARKETING_AGENT_SEARCH_PROVIDER`` to pin one explicitly. With no key
configured, ``search`` raises ``SearchUnavailable`` and the research agent
degrades to its normal "unavailable" markdown instead of inventing sources.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass

import httpx

DEFAULT_MAX_RESULTS = 6
_TIMEOUT = float(os.environ.get("MARKETING_AGENT_SEARCH_TIMEOUT", "30"))

WEB_SEARCH_TOOL = {
    "name": "web_search",
    "description": (
        "Search the public web and return ranked results with titles, URLs, publication "
        "dates when available, and content snippets. Use one compact query per call; "
        "run a focused follow-up search only if the first result set is thin or off-topic."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The search query, in the language most likely to surface good sources.",
            },
            "max_results": {
                "type": "integer",
                "description": f"How many results to return (1-10, default {DEFAULT_MAX_RESULTS}).",
            },
        },
        "required": ["query"],
    },
}


class SearchUnavailable(RuntimeError):
    """No search provider is configured, or the configured provider failed.

    ``status_code`` is set when the failure came from an HTTP response, which
    lets a provider distinguish a transient capacity error from a bad key.
    """

    def __init__(self, message: str, *, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class SearchResult:
    title: str
    url: str
    snippet: str = ""
    published: str = ""


# --------------------------------------------------------------------------
# Provider selection
# --------------------------------------------------------------------------

# Order matters: auto-detection picks the first configured provider, and the
# dedicated search vendors carry publication dates that Gemini grounding lacks.
_PROVIDER_KEYS = {
    "tavily": "TAVILY_API_KEY",
    "serper": "SERPER_API_KEY",
    "brave": "BRAVE_SEARCH_API_KEY",
    "bocha": "BOCHA_API_KEY",
    "gemini": "GEMINI_API_KEY",
}


def active_provider() -> tuple[str, str] | None:
    """Return ``(provider_name, api_key)`` for the configured provider, or None."""
    pinned = (os.environ.get("MARKETING_AGENT_SEARCH_PROVIDER") or "").strip().lower()
    if pinned:
        key = os.environ.get(_PROVIDER_KEYS.get(pinned, ""), "")
        return (pinned, key) if key else None
    for name, env_var in _PROVIDER_KEYS.items():
        key = os.environ.get(env_var, "").strip()
        if key:
            return name, key
    return None


def is_available() -> bool:
    return active_provider() is not None


def unavailable_reason() -> str:
    pinned = (os.environ.get("MARKETING_AGENT_SEARCH_PROVIDER") or "").strip().lower()
    if pinned and pinned not in _PROVIDER_KEYS:
        return (
            f"MARKETING_AGENT_SEARCH_PROVIDER={pinned!r} is not a known provider. "
            f"Choose one of: {', '.join(_PROVIDER_KEYS)}."
        )
    if pinned:
        return f"MARKETING_AGENT_SEARCH_PROVIDER={pinned!r} is set but {_PROVIDER_KEYS[pinned]} is empty."
    return (
        "No web-search provider is configured. DeepSeek has no built-in web search, so the "
        "research agent needs a search API key: set one of "
        + ", ".join(f"{env} ({name})" for name, env in _PROVIDER_KEYS.items())
        + " in the server environment."
    )


# --------------------------------------------------------------------------
# Providers
# --------------------------------------------------------------------------

def _tavily(key: str, query: str, limit: int) -> list[SearchResult]:
    data = _post(
        "https://api.tavily.com/search",
        json={
            "api_key": key,
            "query": query,
            "max_results": limit,
            "search_depth": "advanced",
            "include_answer": False,
        },
    )
    return [
        SearchResult(
            title=str(item.get("title") or ""),
            url=str(item.get("url") or ""),
            snippet=str(item.get("content") or ""),
            published=str(item.get("published_date") or ""),
        )
        for item in (data.get("results") or [])
    ]


def _serper(key: str, query: str, limit: int) -> list[SearchResult]:
    data = _post(
        "https://google.serper.dev/search",
        json={"q": query, "num": limit},
        headers={"X-API-KEY": key},
    )
    return [
        SearchResult(
            title=str(item.get("title") or ""),
            url=str(item.get("link") or ""),
            snippet=str(item.get("snippet") or ""),
            published=str(item.get("date") or ""),
        )
        for item in (data.get("organic") or [])
    ]


def _brave(key: str, query: str, limit: int) -> list[SearchResult]:
    data = _get(
        "https://api.search.brave.com/res/v1/web/search",
        params={"q": query, "count": limit},
        headers={"X-Subscription-Token": key, "Accept": "application/json"},
    )
    return [
        SearchResult(
            title=str(item.get("title") or ""),
            url=str(item.get("url") or ""),
            snippet=str(item.get("description") or ""),
            published=str(item.get("age") or item.get("page_age") or ""),
        )
        for item in ((data.get("web") or {}).get("results") or [])
    ]


def _bocha(key: str, query: str, limit: int) -> list[SearchResult]:
    data = _post(
        "https://api.bochaai.com/v1/web-search",
        json={"query": query, "count": limit, "summary": True},
        headers={"Authorization": f"Bearer {key}"},
    )
    pages = (((data.get("data") or {}).get("webPages") or {}).get("value")) or []
    return [
        SearchResult(
            title=str(item.get("name") or ""),
            url=str(item.get("url") or ""),
            snippet=str(item.get("summary") or item.get("snippet") or ""),
            published=str(item.get("datePublished") or ""),
        )
        for item in pages
    ]


# Gemini grounding returns links as Vertex redirect URLs. Source-tier scoring and
# the UI's citation capsules both key off the real domain, so the redirects have
# to be resolved before results leave this module.
_GEMINI_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
_GEMINI_MODEL = os.environ.get("MARKETING_AGENT_GEMINI_SEARCH_MODEL", "gemini-flash-lite-latest")
_REDIRECT_HOST = "vertexaisearch.cloud.google.com"
# Grounding runs a full model generation before it returns links, so it needs a
# much longer budget than a plain search API. Resolution stays short: a slow
# publisher should not hold up the whole result set.
_GEMINI_TIMEOUT = float(os.environ.get("MARKETING_AGENT_GEMINI_SEARCH_TIMEOUT", "90"))
# Google returns 503 UNAVAILABLE on transient model-capacity spikes; one
# retry turns a failed research turn into a slightly slower one.
_GEMINI_RETRY_STATUSES = (429, 500, 502, 503, 504)
_GEMINI_ATTEMPTS = 2
_GEMINI_RETRY_DELAY_SECONDS = 2.0
_RESOLVE_TIMEOUT = 10.0
_RESOLVE_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0 Safari/537.36"
)


def _resolve_redirect(client: httpx.Client, url: str) -> str:
    """Follow a grounding redirect to the publisher's URL, or keep the redirect."""
    if _REDIRECT_HOST not in url:
        return url
    try:
        response = client.head(url)
        return str(response.url)
    except httpx.HTTPError:
        # Still clickable, just scores as an unknown domain. Better than dropping
        # the source entirely.
        return url


def _post_with_retry(url: str, body: dict, key: str) -> dict:
    """POST to Gemini, retrying once on a transient capacity error."""
    last: SearchUnavailable | None = None
    for attempt in range(_GEMINI_ATTEMPTS):
        try:
            return _post(url, json=body, headers={"x-goog-api-key": key}, timeout=_GEMINI_TIMEOUT)
        except SearchUnavailable as exc:
            last = exc
            if exc.status_code not in _GEMINI_RETRY_STATUSES:
                raise
            if attempt + 1 < _GEMINI_ATTEMPTS:
                time.sleep(_GEMINI_RETRY_DELAY_SECONDS)
    assert last is not None
    raise last


def _gemini(key: str, query: str, limit: int) -> list[SearchResult]:
    """Search via Gemini's Google Search grounding.

    Note the one real gap versus a dedicated search API: grounding chunks carry
    no publication date, so ``published`` is left empty. The prompt asks the
    model to state dates inline instead, which lands them in the snippet where
    the research agent can still read them.
    """
    prompt = (
        f"Search the web for current information about: {query}\n\n"
        "Summarize what you find in 4-8 sentences. Be specific with figures and "
        "named sources, and state the publication date of anything time-sensitive."
    )
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "tools": [{"google_search": {}}],
    }
    url = _GEMINI_ENDPOINT.format(model=_GEMINI_MODEL)
    data = _post_with_retry(url, body, key)

    candidates = data.get("candidates") or []
    if not candidates:
        return []
    metadata = candidates[0].get("groundingMetadata") or {}
    chunks = metadata.get("groundingChunks") or []
    if not chunks:
        # The model answered from parametric memory without searching. Returning
        # nothing is correct: those claims are not sourced.
        return []

    # Map chunk index -> the answer sentences that cite it, which makes a far more
    # relevant snippet than a generic page description would.
    snippets: dict[int, list[str]] = {}
    for support in metadata.get("groundingSupports") or []:
        text = ((support.get("segment") or {}).get("text") or "").strip()
        if not text:
            continue
        for index in support.get("groundingChunkIndices") or []:
            snippets.setdefault(int(index), []).append(text)

    results: list[SearchResult] = []
    seen: set[str] = set()
    # Some publishers serve a different redirect target to non-browser clients, so
    # resolution goes out with a browser User-Agent.
    with httpx.Client(
        follow_redirects=True,
        timeout=_RESOLVE_TIMEOUT,
        headers={"User-Agent": _RESOLVE_USER_AGENT},
    ) as client:
        for index, chunk in enumerate(chunks):
            web = chunk.get("web") or {}
            raw_url = str(web.get("uri") or "").strip()
            if not raw_url:
                continue
            url = _resolve_redirect(client, raw_url)
            if url in seen:
                continue
            seen.add(url)
            results.append(
                SearchResult(
                    title=str(web.get("title") or "").strip() or url,
                    url=url,
                    snippet=" ".join(snippets.get(index, []))[:800],
                    published="",
                )
            )
            if len(results) >= limit:
                break
    return results


_PROVIDERS = {
    "tavily": _tavily,
    "serper": _serper,
    "brave": _brave,
    "bocha": _bocha,
    "gemini": _gemini,
}


def _post(url: str, *, json: dict, headers: dict | None = None, timeout: float | None = None) -> dict:
    try:
        response = httpx.post(url, json=json, headers=headers, timeout=timeout or _TIMEOUT)
        response.raise_for_status()
        return response.json()
    except httpx.HTTPStatusError as exc:
        raise SearchUnavailable(
            f"{url} returned {exc.response.status_code}: {exc.response.text[:200]}",
            status_code=exc.response.status_code,
        ) from exc
    except (httpx.HTTPError, ValueError) as exc:
        raise SearchUnavailable(f"search request to {url} failed: {exc}") from exc


def _get(url: str, *, params: dict, headers: dict | None = None) -> dict:
    try:
        response = httpx.get(url, params=params, headers=headers, timeout=_TIMEOUT)
        response.raise_for_status()
        return response.json()
    except httpx.HTTPStatusError as exc:
        raise SearchUnavailable(
            f"{url} returned {exc.response.status_code}: {exc.response.text[:200]}",
            status_code=exc.response.status_code,
        ) from exc
    except (httpx.HTTPError, ValueError) as exc:
        raise SearchUnavailable(f"search request to {url} failed: {exc}") from exc


# --------------------------------------------------------------------------
# Public entry points
# --------------------------------------------------------------------------

def search(query: str, max_results: int = DEFAULT_MAX_RESULTS) -> list[SearchResult]:
    """Run one search. Raises ``SearchUnavailable`` when unconfigured or failing."""
    query = (query or "").strip()
    if not query:
        return []
    selected = active_provider()
    if selected is None:
        raise SearchUnavailable(unavailable_reason())
    name, key = selected
    provider = _PROVIDERS.get(name)
    if provider is None:
        raise SearchUnavailable(unavailable_reason())
    limit = max(1, min(int(max_results or DEFAULT_MAX_RESULTS), 10))
    results = [r for r in provider(key, query, limit) if r.url]
    return results[:limit]


def format_results(query: str, results: list[SearchResult]) -> str:
    """Render results as markdown for the model to read and cite."""
    if not results:
        return f'No results for "{query}". Try a different query or a broader time window.'
    lines = [f'Search results for "{query}":', ""]
    for index, item in enumerate(results, start=1):
        header = f"{index}. {item.title or item.url}"
        if item.published:
            header += f" — {item.published}"
        lines.append(header)
        lines.append(f"   URL: {item.url}")
        if item.snippet:
            lines.append(f"   {item.snippet.strip()[:800]}")
        lines.append("")
    return "\n".join(lines).strip()


def handle_web_search(payload: dict) -> str:
    """Tool handler for ``run_agent``'s ``client_tool_handlers``."""
    query = str(payload.get("query") or "").strip()
    if not query:
        return "Error: web_search requires a non-empty 'query'."
    try:
        results = search(query, int(payload.get("max_results") or DEFAULT_MAX_RESULTS))
    except SearchUnavailable as exc:
        return f"Error: web search is unavailable — {exc}"
    except Exception as exc:  # noqa: BLE001 — a bad search must not kill the turn
        return f"Error: web search failed — {exc}"
    return format_results(query, results)
