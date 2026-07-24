from __future__ import annotations

import unittest
from unittest import mock

from server import db, embeddings, kb_retrieval, query_rewrite, reranker, sessions

ID_ALICE = "11010519491231002X"


class KbRetrievalTests(unittest.TestCase):
    def setUp(self) -> None:
        sessions.reset_for_tests()
        db.init()
        # one user + org + a couple of documents
        import time
        import uuid

        self.uid = uuid.uuid4().hex
        with db._connect() as c:
            c.execute(
                "INSERT INTO users (id,account,password_hash,username,real_name,id_card,created_at,updated_at)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (self.uid, "a@x.com", "x", "Alice", "Alice", "0" * 18, time.time(), time.time()),
            )
        self.org = db.create_org(self.uid, "Org")
        db.create_kb_document(
            self.org["id"], self.uid, "报销制度",
            "公司报销需在 30 天内提交发票，交通费上限 500 元。",
            chunks=["公司报销需在 30 天内提交发票。", "交通费每日上限 500 元。"],
        )
        db.create_kb_document(
            self.org["id"], self.uid, "考勤制度",
            "每天工作 8 小时，迟到超过 30 分钟记为旷工。",
            chunks=["每天工作 8 小时。", "迟到超过 30 分钟记为旷工。"],
        )

    def tearDown(self) -> None:
        sessions.reset_for_tests()
        embeddings.reset_for_tests()
        reranker.reset_for_tests()

    # ----- unit: fusion & tokenization -----

    def test_rrf_fuse_prefers_agreement(self) -> None:
        a = [("x", 9.0), ("y", 1.0)]
        b = [("y", 9.0), ("x", 1.0)]
        fused = kb_retrieval._rrf_fuse(a, b)
        self.assertEqual(set(fused), {"x", "y"})

    def test_tokenize_handles_cjk_and_latin(self) -> None:
        toks = kb_retrieval._tokenize("报销 travel")
        self.assertIn("travel", toks)
        self.assertIn("报销", toks)

    # ----- lexical-only (no embeddings, no rerank, no rewrite) -----

    def test_lexical_only_pipeline(self) -> None:
        with mock.patch.object(embeddings, "is_available", return_value=False), mock.patch.object(
            reranker, "is_available", return_value=False
        ), mock.patch.object(
            query_rewrite, "rewrite_query", return_value={"resolved": "报销 发票", "expansions": [], "intent": "policy_lookup", "source": "test"}
        ):
            out = kb_retrieval.retrieve(self.org["id"], "报销 发票", limit=3)
        self.assertEqual(out["method"], "bm25")
        self.assertTrue(out["results"])
        self.assertEqual(out["results"][0]["title"], "报销制度")

    # ----- hybrid: injected fake embeddings + fake reranker -----

    def test_hybrid_with_fake_embeddings_and_rerank(self) -> None:
        # Fake embedding: map any text to a vector by keyword presence.
        def fake_embed_texts(texts):
            return [[1.0 if "报销" in t or "发票" in t else 0.0,
                     1.0 if "交通" in t else 0.0,
                     1.0 if "迟到" in t or "考勤" in t else 0.0] for t in texts]

        # Re-embed the corpus so chunks carry vectors matching the fake scheme.
        with mock.patch.object(embeddings, "embed_texts", side_effect=fake_embed_texts), \
             mock.patch.object(embeddings, "is_available", return_value=True):
            # rebuild docs with embeddings
            sessions.reset_for_tests(); db.init()
            import time, uuid
            uid = uuid.uuid4().hex
            with db._connect() as c:
                c.execute("INSERT INTO users (id,account,password_hash,username,real_name,id_card,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?)",
                          (uid,"a@x.com","x","Alice","Alice","0"*18,time.time(),time.time()))
            org = db.create_org(uid, "Org")
            chunks = ["公司报销需在 30 天内提交发票。", "迟到超过 30 分钟记为旷工。"]
            db.create_kb_document(org["id"], uid, "混合制度", "".join(chunks), chunks=chunks,
                                  embeddings=fake_embed_texts(chunks))

            with mock.patch.object(reranker, "is_available", return_value=True), \
                 mock.patch.object(reranker, "rerank", side_effect=lambda q, ps: [1.0 if "报销" in p else 0.0 for p in ps]), \
                 mock.patch.object(query_rewrite, "rewrite_query", return_value={"resolved": "报销 发票", "expansions": ["费用"], "intent": "policy_lookup", "source": "test"}):
                out = kb_retrieval.retrieve(org["id"], "报销", limit=2)

        self.assertIn("hybrid", out["method"])
        self.assertIn("rerank", out["method"])
        self.assertIn("报销", out["results"][0]["text"])

    # ----- query rewrite graceful degrade -----

    def test_query_rewrite_degrades_without_llm(self) -> None:
        import os

        with mock.patch.dict(os.environ, {"MARKETING_AGENT_KB_QUERY_REWRITE": "0"}):
            rw = query_rewrite.rewrite_query("它的上限是多少", history=[{"role": "user", "text": "交通费怎么报"}])
        self.assertEqual(rw["resolved"], "它的上限是多少")
        self.assertEqual(rw["intent"], "unknown")

    def test_empty_corpus(self) -> None:
        sessions.reset_for_tests(); db.init()
        with mock.patch.object(query_rewrite, "rewrite_query", return_value={"resolved": "x", "expansions": [], "intent": "other", "source": "test"}):
            out = kb_retrieval.retrieve("no-such-org", "anything")
        self.assertEqual(out["results"], [])


if __name__ == "__main__":
    unittest.main()
