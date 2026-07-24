"""Knowledge-base retrieval pipeline.

    query
      → query_rewrite (coreference + synonym expansion + intent)
      → dual recall:  BM25 lexical  +  vector cosine (local embeddings)
      → RRF fusion
      → cross-encoder rerank
      → top-k passages

Every stage degrades independently: no embeddings → lexical only; no reranker →
fused order; no rewrite LLM → raw query. With nothing available it is exactly the
old lexical search, so retrieval never hard-fails.
"""
from __future__ import annotations

import math
import re
from typing import Any

from . import db, embeddings, query_rewrite, reranker

_BM25_K1 = 1.5
_BM25_B = 0.75
_RRF_K = 60
_RERANK_CANDIDATES = 20


def _tokenize(text: str) -> list[str]:
    """Terms + CJK bigrams, preserving repetition (for term frequencies)."""
    q = (text or "").lower()
    tokens: list[str] = []
    for word in re.split(r"[^0-9a-z一-鿿]+", q):
        if len(word) >= 2 and not all("一" <= ch <= "鿿" for ch in word):
            tokens.append(word)
    cjk = [ch for ch in q if "一" <= ch <= "鿿"]
    for i in range(len(cjk) - 1):
        tokens.append(cjk[i] + cjk[i + 1])
    return tokens


def _bm25_rank(chunks: list[dict], query_terms: list[str]) -> list[tuple[str, float]]:
    if not query_terms:
        return []
    tokenized = [_tokenize(c["text"]) for c in chunks]
    lengths = [len(t) for t in tokenized]
    avglen = (sum(lengths) / len(lengths)) if lengths else 0.0
    n = len(chunks)
    df: dict[str, int] = {}
    for toks in tokenized:
        for term in set(toks):
            df[term] = df.get(term, 0) + 1
    q_set = set(query_terms)
    scored: list[tuple[str, float]] = []
    for i, c in enumerate(chunks):
        toks = tokenized[i]
        if not toks:
            continue
        tf: dict[str, int] = {}
        for t in toks:
            if t in q_set:
                tf[t] = tf.get(t, 0) + 1
        if not tf:
            continue
        score = 0.0
        for term, freq in tf.items():
            idf = math.log(1 + (n - df[term] + 0.5) / (df[term] + 0.5))
            denom = freq + _BM25_K1 * (1 - _BM25_B + _BM25_B * (lengths[i] / avglen if avglen else 1))
            score += idf * (freq * (_BM25_K1 + 1)) / denom
        if score > 0:
            scored.append((_key(c), score))
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored


def _vector_rank(chunks: list[dict], query: str) -> list[tuple[str, float]]:
    if not embeddings.is_available():
        return []
    qvec = embeddings.embed_one(query)
    if qvec is None:
        return []
    scored: list[tuple[str, float]] = []
    for c in chunks:
        emb = c.get("embedding")
        if not emb:
            continue
        scored.append((_key(c), _cosine(qvec, emb)))
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored


def _cosine(a: list[float], b: list[float]) -> float:
    # Embeddings are stored normalized, but normalize defensively anyway.
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)


def _rrf_fuse(*rankings: list[tuple[str, float]]) -> list[str]:
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, (key, _score) in enumerate(ranking):
            scores[key] = scores.get(key, 0.0) + 1.0 / (_RRF_K + rank + 1)
    return [k for k, _ in sorted(scores.items(), key=lambda x: x[1], reverse=True)]


def _key(chunk: dict) -> str:
    return f"{chunk['doc_id']}#{chunk['chunk_index']}"


def retrieve(
    org_id: str | None,
    query: str,
    history: list[dict] | None = None,
    limit: int = 5,
    locale: str = "zh",
    user_id: str | None = None,
) -> dict:
    """Run the full pipeline over the org's shared docs + the user's personal docs.
    Returns ``{results, rewrite, method}``."""
    query = (query or "").strip()
    if not query:
        return {"results": [], "rewrite": None, "method": "empty"}

    chunks = db.list_kb_chunks_for_org(org_id, user_id)
    if not chunks:
        rw = query_rewrite.rewrite_query(query, history, locale)
        return {"results": [], "rewrite": rw, "method": "empty_corpus"}

    rw = query_rewrite.rewrite_query(query, history, locale)
    resolved = rw["resolved"]
    search_text = resolved + " " + " ".join(rw.get("expansions", []))

    by_key = {_key(c): c for c in chunks}
    lexical = _bm25_rank(chunks, _tokenize(search_text))
    vector = _vector_rank(chunks, resolved)

    methods = []
    if vector:
        methods.append("vector")
    if lexical:
        methods.append("bm25")

    if lexical and vector:
        fused = _rrf_fuse(lexical, vector)
        method = "hybrid"
    elif vector:
        fused = [k for k, _ in vector]
        method = "vector"
    else:
        fused = [k for k, _ in lexical]
        method = "bm25"

    if not fused:
        return {"results": [], "rewrite": rw, "method": "no_match"}

    candidate_keys = fused[:_RERANK_CANDIDATES]
    candidates = [by_key[k] for k in candidate_keys]

    scores = reranker.rerank(resolved, [c["text"] for c in candidates])
    if scores is not None:
        order = sorted(range(len(candidates)), key=lambda i: scores[i], reverse=True)
        candidates = [candidates[i] for i in order]
        method = method + "+rerank"

    results = [
        {"doc_id": c["doc_id"], "chunk_index": c["chunk_index"], "title": c["title"], "text": c["text"]}
        for c in candidates[:limit]
    ]
    return {"results": results, "rewrite": rw, "method": method}


def embed_chunks(chunks: list[str]) -> list[list[float]] | None:
    """Embed chunks for ingestion. Returns None if embeddings unavailable."""
    return embeddings.embed_texts(chunks)
