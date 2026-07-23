from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from server import db, memory, sessions, uploads
from server.main import app


class RouteTests(unittest.TestCase):
    def setUp(self) -> None:
        sessions.reset_for_tests()
        os.environ["ANTHROPIC_API_KEY"] = "test-key"
        # Deterministic heuristic extraction; never call the model in tests.
        os.environ["MARKETING_AGENT_MEMORY_LLM"] = "0"
        self.upload_tmp = tempfile.TemporaryDirectory()
        self.old_upload_dir = uploads.UPLOAD_DIR
        uploads.UPLOAD_DIR = Path(self.upload_tmp.name)
        self.client = TestClient(app)
        self.headers = self._register("alice@example.com")

    def tearDown(self) -> None:
        uploads.UPLOAD_DIR = self.old_upload_dir
        self.upload_tmp.cleanup()
        sessions.reset_for_tests()

    def _register(self, account: str) -> dict[str, str]:
        response = self.client.post(
            "/api/auth/register",
            json={
                "account": account,
                "password": "password123",
                "username": account.split("@", 1)[0].title(),
                "real_name": "张三",
                "id_card": "11010519491231002X",
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        return {"Authorization": f"Bearer {response.json()['token']}"}

    def _create_session(self, headers: dict[str, str] | None = None) -> str:
        created = self.client.post("/api/sessions", headers=headers or self.headers)
        self.assertEqual(created.status_code, 200, created.text)
        return created.json()["session_id"]

    def test_health(self) -> None:
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    def test_auth_me_and_duplicate_registration(self) -> None:
        duplicate = self.client.post(
            "/api/auth/register",
            json={
                "account": "ALICE@EXAMPLE.COM",
                "password": "password123",
                "username": "Alice",
                "real_name": "张三",
                "id_card": "11010519491231002X",
            },
        )
        self.assertEqual(duplicate.status_code, 409)

        me = self.client.get("/api/auth/me", headers=self.headers)
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.json()["user"]["account"], "alice@example.com")
        self.assertEqual(me.json()["user"]["id_card_masked"], "11010*********002X")

    def test_invalid_id_card_rejected(self) -> None:
        response = self.client.post(
            "/api/auth/register",
            json={
                "account": "badid@example.com",
                "password": "password123",
                "username": "Bad",
                "real_name": "李四",
                "id_card": "110105194912310021",
            },
        )
        self.assertEqual(response.status_code, 400)

    def test_account_must_be_email_or_phone(self) -> None:
        response = self.client.post(
            "/api/auth/register",
            json={
                "account": "plain_user",
                "password": "password123",
                "username": "Plain",
                "real_name": "Li Si",
                "id_card": "11010519491231002X",
            },
        )
        self.assertEqual(response.status_code, 400)

    def test_phone_account_can_login(self) -> None:
        headers = self._register("13900139000")
        login = self.client.post(
            "/api/auth/login",
            json={"account": "13900139000", "password": "password123"},
        )
        self.assertEqual(login.status_code, 200)
        me = self.client.get("/api/auth/me", headers=headers)
        self.assertEqual(me.json()["user"]["account"], "13900139000")

    def test_login_distinguishes_missing_account_and_bad_password(self) -> None:
        missing = self.client.post(
            "/api/auth/login",
            json={"account": "missing@example.com", "password": "password123"},
        )
        self.assertEqual(missing.status_code, 404)
        self.assertEqual(missing.json()["detail"], "账号不存在。")

        bad_password = self.client.post(
            "/api/auth/login",
            json={"account": "alice@example.com", "password": "wrong-password"},
        )
        self.assertEqual(bad_password.status_code, 401)
        self.assertEqual(bad_password.json()["detail"], "密码不正确。")

    def test_business_routes_require_auth(self) -> None:
        response = self.client.get("/api/sessions")
        self.assertEqual(response.status_code, 401)

    def test_marketing_memory_can_be_managed(self) -> None:
        empty = self.client.get("/api/memory/marketing", headers=self.headers)
        self.assertEqual(empty.status_code, 200, empty.text)
        self.assertEqual(empty.json()["profile"]["industry"], [])
        self.assertTrue(empty.json()["enabled"])

        saved = self.client.put(
            "/api/memory/marketing",
            headers=self.headers,
            json={
                "profile": {
                    "role_title": ["Marketing lead"],
                    "industry": ["B2B SaaS"],
                    "channels": "LinkedIn\nEmail",
                    "target_customers": ["Enterprise buyers"],
                }
            },
        )
        self.assertEqual(saved.status_code, 200, saved.text)
        body = saved.json()
        self.assertEqual(body["profile"]["industry"], ["B2B SaaS"])
        self.assertEqual(body["profile"]["channels"], ["LinkedIn", "Email"])

        # A manual save is authoritative and must reset accumulated evidence so
        # edited-away values cannot immediately re-promote.
        user_id = db.get_user_by_account("alice@example.com")["id"]
        db.add_user_marketing_memory_evidence(user_id, [("channels", "LinkedIn", False)])
        self.assertTrue(db.list_user_marketing_memory_evidence(user_id))
        self.client.put(
            "/api/memory/marketing",
            headers=self.headers,
            json={"profile": {"industry": ["B2B SaaS"]}},
        )
        self.assertEqual(db.list_user_marketing_memory_evidence(user_id), [])

        other_headers = self._register("memory-other@example.com")
        other = self.client.get("/api/memory/marketing", headers=other_headers)
        self.assertEqual(other.status_code, 200, other.text)
        self.assertEqual(other.json()["profile"]["industry"], [])

        cleared = self.client.delete("/api/memory/marketing", headers=self.headers)
        self.assertEqual(cleared.status_code, 200, cleared.text)
        self.assertEqual(cleared.json()["profile"]["channels"], [])

        disabled = self.client.patch("/api/memory/marketing", headers=self.headers, json={"enabled": False})
        self.assertEqual(disabled.status_code, 200, disabled.text)
        self.assertFalse(disabled.json()["enabled"])

        loaded = self.client.get("/api/memory/marketing", headers=self.headers)
        self.assertEqual(loaded.status_code, 200, loaded.text)
        self.assertFalse(loaded.json()["enabled"])

    def test_marketing_memory_evidence_endpoint(self) -> None:
        user_id = db.get_user_by_account("alice@example.com")["id"]
        db.add_user_marketing_memory_evidence(
            user_id,
            [("channels", "LinkedIn", False), ("products", "牙科诊所预约系统", True)],
        )

        response = self.client.get("/api/memory/marketing/evidence", headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["threshold"], memory.LONG_TERM_EVIDENCE_THRESHOLD)
        by_value = {item["value"]: item for item in body["evidence"]}
        # Explicit self-declaration is promoted immediately; incidental is not.
        self.assertTrue(by_value["牙科诊所预约系统"]["promoted"])
        self.assertTrue(by_value["牙科诊所预约系统"]["explicit"])
        self.assertFalse(by_value["LinkedIn"]["promoted"])
        # And the learned profile reflects the promoted value.
        learned = self.client.get("/api/memory/marketing", headers=self.headers).json()["learned"]
        self.assertIn("牙科诊所预约系统", learned["products"])

    def test_session_create_delete(self) -> None:
        created = self.client.post("/api/sessions", headers=self.headers)
        self.assertEqual(created.status_code, 200)
        session_id = created.json()["session_id"]
        self.assertTrue(sessions.exists(session_id))

        deleted = self.client.delete(f"/api/sessions/{session_id}", headers=self.headers)
        self.assertEqual(deleted.status_code, 200)
        self.assertFalse(sessions.exists(session_id))

    def test_upload_csv_success(self) -> None:
        response = self.client.post(
            "/api/upload",
            headers=self.headers,
            files={"file": ("campaign.csv", b"channel,clicks\nsearch,10\n", "text/csv")},
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertRegex(body["file_id"], r"^[0-9a-f]{32}$")
        self.assertEqual(body["original_name"], "campaign.csv")
        self.assertEqual(body["size"], 25)

    def test_upload_empty_file(self) -> None:
        response = self.client.post(
            "/api/upload",
            headers=self.headers,
            files={"file": ("empty.csv", b"", "text/csv")},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "Empty file.")

    def test_upload_rejects_unsupported_extension(self) -> None:
        response = self.client.post(
            "/api/upload",
            headers=self.headers,
            files={"file": ("notes.txt", b"a,b\n1,2\n", "text/plain")},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("Unsupported file type", response.json()["detail"])

    def test_upload_accepts_pdf(self) -> None:
        response = self.client.post(
            "/api/upload",
            headers=self.headers,
            files={"file": ("brief.pdf", b"%PDF-1.4 minimal", "application/pdf")},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["mime"], "application/pdf")

    def test_upload_rejects_oversized_csv(self) -> None:
        oversized = b"a" * (uploads.MAX_UPLOAD_BYTES + 1)
        response = self.client.post(
            "/api/upload",
            headers=self.headers,
            files={"file": ("large.csv", oversized, "text/csv")},
        )
        self.assertEqual(response.status_code, 413)

    def test_stream_rejects_invalid_csv_id(self) -> None:
        session_id = self._create_session()

        response = self.client.get(
            f"/api/sessions/{session_id}/stream",
            headers=self.headers,
            params={"prompt": "Analyze this", "csv_id": "not-a-real-id"},
        )
        self.assertEqual(response.status_code, 404)

    def test_session_messages_include_artifacts(self) -> None:
        session_id = self._create_session()
        db_path = Path(self.upload_tmp.name) / "artifact.pdf"
        db_path.write_bytes(b"%PDF-1.4")
        from server import db

        user_id = db.get_user_by_account("alice@example.com")["id"]
        db.add_message(session_id, "user", "make a pdf")
        db.add_message(session_id, "assistant", "PDF generated.")
        rec = db.add_artifact(
            user_id=user_id,
            session_id=session_id,
            kind="pdf",
            filename="Campaign.pdf",
            mime="application/pdf",
            path=str(db_path),
        )

        response = self.client.get(f"/api/sessions/{session_id}/messages", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        messages = response.json()["messages"]
        self.assertEqual(messages[-1]["role"], "assistant")
        self.assertEqual(
            messages[-1]["artifacts"],
            [
                {
                    "artifact_id": rec["id"],
                    "filename": "Campaign.pdf",
                    "mime": "application/pdf",
                }
            ],
        )

    def test_stream_errors_are_persisted_to_history(self) -> None:
        from server import streaming

        old_run_orchestrator = streaming.run_orchestrator

        def fail_orchestrator(*args, **kwargs) -> None:  # noqa: ANN002, ANN003
            raise RuntimeError("model unavailable")

        streaming.run_orchestrator = fail_orchestrator
        try:
            session_id = self._create_session()

            with self.client.stream(
                "GET",
                f"/api/sessions/{session_id}/stream",
                headers=self.headers,
                params={"prompt": "write a post"},
            ) as response:
                self.assertEqual(response.status_code, 200)
                body = response.read().decode("utf-8")

            self.assertIn('"event": "error"', body)
            messages = self.client.get(f"/api/sessions/{session_id}/messages", headers=self.headers).json()["messages"]
            self.assertEqual(messages[-1]["role"], "assistant")
            self.assertEqual(messages[-1]["content"], "**Error:** model unavailable")
        finally:
            streaming.run_orchestrator = old_run_orchestrator

    def test_complete_session_returns_non_streamed_result(self) -> None:
        from server import routes

        old_run_orchestrator = routes.run_orchestrator

        def complete_orchestrator(client, conversation, prompt, on_event) -> None:
            on_event("result", {"text": "Done without streaming."})

        routes.run_orchestrator = complete_orchestrator
        try:
            session_id = self._create_session()

            response = self.client.post(
                f"/api/sessions/{session_id}/complete",
                headers=self.headers,
                json={"prompt": "write a post"},
            )

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["text"], "Done without streaming.")
            messages = self.client.get(f"/api/sessions/{session_id}/messages", headers=self.headers).json()["messages"]
            self.assertEqual(messages[-1]["role"], "assistant")
            self.assertEqual(messages[-1]["content"], "Done without streaming.")
        finally:
            routes.run_orchestrator = old_run_orchestrator

    def test_chinese_prompt_defaults_pdf_deliverable_to_chinese(self) -> None:
        from server import routes

        self.assertEqual(routes._output_language_for_prompt("请帮我生成竞品分析 PDF"), "zh")
        self.assertEqual(routes._output_language_for_prompt("请用英文生成竞品分析 PDF"), "en")

        sections = routes._pdf_sections_from_markdown("正文内容", output_language="zh")
        self.assertEqual(sections[0]["heading"], "摘要")

    def _save_news_config(self, headers: dict[str, str]) -> dict:
        response = self.client.put(
            "/api/news/config",
            headers=headers,
            json={
                "industry": "AI marketing",
                "detail_level": "brief",
                "summary_time": "09:00",
                "timezone": "UTC",
                "language": "zh",
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["config"]

    def test_news_cancel_keeps_content_then_reactivates(self) -> None:
        config = self._save_news_config(self.headers)
        me = self.client.get("/api/auth/me", headers=self.headers).json()["user"]
        db.add_news_summary(
            me["id"], config["id"], "## Summary\nheld content",
            generated_at=1.0, window_start=0.0, window_end=1.0,
        )

        cancelled = self.client.post("/api/news/cancel", headers=self.headers)
        self.assertEqual(cancelled.status_code, 200, cancelled.text)
        body = cancelled.json()["config"]
        self.assertFalse(body["enabled"])
        self.assertIsNotNone(body["cancelled_at"])
        self.assertIn("revert_at", body)

        # Within the window: config still visible (disabled), content retained.
        cfg = self.client.get("/api/news/config", headers=self.headers).json()["config"]
        self.assertFalse(cfg["enabled"])
        self.assertIsNotNone(cfg["revert_at"])
        summary = self.client.get("/api/news/summary", headers=self.headers).json()["summary"]
        self.assertEqual(summary["summary"], "## Summary\nheld content")

        # Manual refresh is blocked while cancelled.
        blocked = self.client.post("/api/news/refresh", headers=self.headers)
        self.assertEqual(blocked.status_code, 409)

        # Saving a new task reactivates and clears the cancellation.
        reactivated = self._save_news_config(self.headers)
        self.assertTrue(reactivated["enabled"])
        self.assertIsNone(reactivated["cancelled_at"])

    def test_news_cancel_reverts_to_empty_after_deadline(self) -> None:
        self._save_news_config(self.headers)
        me = self.client.get("/api/auth/me", headers=self.headers).json()["user"]
        db.add_news_summary(
            me["id"], None, "## Summary\nold",
            generated_at=1.0, window_start=0.0, window_end=1.0,
        )
        self.client.post("/api/news/cancel", headers=self.headers)
        # Force the cancellation well into the past so it is expired.
        db.cancel_news_config(me["id"], 1000.0)

        cfg = self.client.get("/api/news/config", headers=self.headers).json()["config"]
        self.assertIsNone(cfg)
        summary = self.client.get("/api/news/summary", headers=self.headers).json()["summary"]
        self.assertIsNone(summary)

    def test_news_cancel_requires_existing_config(self) -> None:
        response = self.client.post("/api/news/cancel", headers=self.headers)
        self.assertEqual(response.status_code, 400)

    # ---------- marketing image ----------

    def _upload_png(self, headers: dict[str, str] | None = None) -> str:
        png = (
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00"
            b"\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00"
            b"\x00IEND\xaeB`\x82"
        )
        res = self.client.post(
            "/api/upload",
            headers=headers or self.headers,
            files={"file": ("product.png", png, "image/png")},
        )
        self.assertEqual(res.status_code, 200, res.text)
        return res.json()["file_id"]

    def test_upload_accepts_webp(self) -> None:
        res = self.client.post(
            "/api/upload",
            headers=self.headers,
            files={"file": ("shot.webp", b"RIFF....WEBP", "image/webp")},
        )
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(res.json()["mime"], "image/webp")

    def test_image_endpoints_require_auth(self) -> None:
        self.assertEqual(self.client.get("/api/image/history").status_code, 401)
        self.assertEqual(self.client.get("/api/image/skills").status_code, 401)

    def test_image_skills_and_templates(self) -> None:
        skills = self.client.get("/api/image/skills", headers=self.headers).json()["skills"]
        self.assertTrue(any(s["id"] == "taobao" for s in skills))
        tpls = self.client.get(
            "/api/image/templates", headers=self.headers, params={"platform": "taobao"}
        ).json()["templates"]
        self.assertTrue(tpls and all(t["platform"] == "taobao" for t in tpls))

    def test_image_generate_persists_and_previews(self) -> None:
        from server import routes

        file_id = self._upload_png()
        fake = {
            "ok": True,
            "filename": "marketing_taobao.png",
            "mime": "image/png",
            "path": str(Path(self.upload_tmp.name) / "gen.png"),
        }
        Path(fake["path"]).write_bytes(b"\x89PNG\r\n\x1a\n")
        with mock.patch.object(routes.image_gen, "generate_image", return_value=fake):
            res = self.client.post(
                "/api/image/generate",
                headers=self.headers,
                json={"prompt": "nice bottle", "style_key": "taobao",
                      "source": {"type": "upload", "id": file_id}},
            )
        self.assertEqual(res.status_code, 200, res.text)
        body = res.json()
        self.assertTrue(body["ok"])
        aid = body["artifact_id"]
        self.assertEqual(self.client.get(f"/api/artifacts/{aid}/preview", headers=self.headers).status_code, 200)
        hist = self.client.get("/api/image/history", headers=self.headers).json()["history"]
        self.assertEqual(len(hist), 1)
        self.assertEqual(hist[0]["artifact_id"], aid)

    def test_image_generate_unavailable_returns_graceful_200(self) -> None:
        from server import routes

        unavailable = {"ok": False, "unavailable": True, "message": "## Image Unavailable\n\nno key"}
        with mock.patch.object(routes.image_gen, "generate_image", return_value=unavailable):
            res = self.client.post(
                "/api/image/generate",
                headers=self.headers,
                json={"prompt": "x"},
            )
        self.assertEqual(res.status_code, 200)
        self.assertFalse(res.json()["ok"])
        self.assertTrue(res.json()["unavailable"])

    def test_image_process_object_and_screenshot(self) -> None:
        from server import routes

        file_id = self._upload_png()
        obj = {"classification": "object", "original_png": b"x", "cutout_png": b"CUT", "warning": None}
        with mock.patch.object(routes.image_processing, "process_upload", return_value=obj):
            res = self.client.post("/api/image/process", headers=self.headers, json={"file_id": file_id})
        self.assertEqual(res.status_code, 200, res.text)
        body = res.json()
        self.assertEqual(body["classification"], "object")
        self.assertIsNotNone(body["cutout"])
        self.assertEqual(
            self.client.get(f"/api/artifacts/{body['cutout']['artifact_id']}/preview", headers=self.headers).status_code,
            200,
        )

        shot = {"classification": "screenshot", "original_png": b"x", "cutout_png": None, "warning": None}
        with mock.patch.object(routes.image_processing, "process_upload", return_value=shot):
            res2 = self.client.post("/api/image/process", headers=self.headers, json={"file_id": file_id})
        self.assertIsNone(res2.json()["cutout"])

    def test_image_cutout_on_demand(self) -> None:
        from server import routes

        file_id = self._upload_png()
        with mock.patch.object(routes.image_processing, "cutout", return_value=b"\x89PNG\r\n\x1a\n"):
            res = self.client.post("/api/image/cutout", headers=self.headers, json={"file_id": file_id})
        self.assertEqual(res.status_code, 200, res.text)
        body = res.json()
        self.assertIsNotNone(body["artifact_id"])
        self.assertEqual(
            self.client.get(f"/api/artifacts/{body['artifact_id']}/preview", headers=self.headers).status_code,
            200,
        )

    def test_image_cutout_unavailable_is_graceful(self) -> None:
        from server import routes

        file_id = self._upload_png()
        with mock.patch.object(
            routes.image_processing, "cutout",
            side_effect=routes.image_processing.CutoutUnavailable("no rembg"),
        ):
            res = self.client.post("/api/image/cutout", headers=self.headers, json={"file_id": file_id})
        self.assertEqual(res.status_code, 200)
        self.assertIsNone(res.json()["artifact_id"])
        self.assertIn("no rembg", res.json()["warning"])

    def test_image_templates_platform_and_style_filter(self) -> None:
        all_t = self.client.get("/api/image/templates", headers=self.headers).json()["templates"]
        self.assertTrue(any(t["platform"] == "taobao" for t in all_t))
        self.assertTrue(all("style" in t for t in all_t))
        # platform filter
        taobao = self.client.get(
            "/api/image/templates", headers=self.headers, params={"platform": "taobao"}
        ).json()["templates"]
        self.assertTrue(taobao and all(t["platform"] == "taobao" for t in taobao))
        # style filter is a distinct axis
        white = self.client.get(
            "/api/image/templates", headers=self.headers, params={"style": "white"}
        ).json()["templates"]
        self.assertTrue(white and all(t["style"] == "white" for t in white))

    def test_image_compose_save_persists_and_previews(self) -> None:
        file_id = self._upload_png()  # stands in for the client-composed image
        res = self.client.post(
            "/api/image/compose-save",
            headers=self.headers,
            json={"file_id": file_id, "template_id": "t_taobao_white", "style_key": "taobao", "prompt": "新品上市"},
        )
        self.assertEqual(res.status_code, 200, res.text)
        body = res.json()
        self.assertTrue(body["ok"])
        self.assertEqual(
            self.client.get(f"/api/artifacts/{body['artifact_id']}/preview", headers=self.headers).status_code,
            200,
        )
        hist = self.client.get("/api/image/history", headers=self.headers).json()["history"]
        self.assertTrue(any(h["id"] == body["history_id"] and h["params"].get("composed") for h in hist))

    def test_image_compose_save_rejects_cross_user_file(self) -> None:
        file_id = self._upload_png()
        bob = self._register("13800138000")
        res = self.client.post(
            "/api/image/compose-save",
            headers=bob,
            json={"file_id": file_id, "style_key": "taobao"},
        )
        self.assertEqual(res.status_code, 404)

    def test_preview_sets_cache_header(self) -> None:
        file_id = self._upload_png()
        res = self.client.get(f"/api/uploads/{file_id}/preview", headers=self.headers)
        self.assertEqual(res.status_code, 200)
        self.assertIn("max-age", res.headers.get("cache-control", ""))

    def test_image_history_user_isolation(self) -> None:
        from server import routes

        file_id = self._upload_png()
        fake = {"ok": True, "filename": "g.png", "mime": "image/png",
                "path": str(Path(self.upload_tmp.name) / "g.png")}
        Path(fake["path"]).write_bytes(b"\x89PNG\r\n\x1a\n")
        with mock.patch.object(routes.image_gen, "generate_image", return_value=fake):
            hid = self.client.post(
                "/api/image/generate", headers=self.headers,
                json={"prompt": "x", "source": {"type": "upload", "id": file_id}},
            ).json()["history_id"]
        bob = self._register("13800138000")
        self.assertEqual(self.client.get("/api/image/history", headers=bob).json()["history"], [])
        self.assertEqual(self.client.delete(f"/api/image/history/{hid}", headers=bob).status_code, 404)
        self.assertEqual(self.client.delete(f"/api/image/history/{hid}", headers=self.headers).status_code, 200)

    def test_image_reedit_uses_prior_artifact(self) -> None:
        from server import routes

        file_id = self._upload_png()
        gen1 = {"ok": True, "filename": "g1.png", "mime": "image/png",
                "path": str(Path(self.upload_tmp.name) / "g1.png")}
        Path(gen1["path"]).write_bytes(b"\x89PNG\r\n\x1a\n")
        with mock.patch.object(routes.image_gen, "generate_image", return_value=gen1):
            first = self.client.post(
                "/api/image/generate", headers=self.headers,
                json={"prompt": "x", "source": {"type": "upload", "id": file_id}},
            ).json()
        gen2 = {"ok": True, "filename": "g2.png", "mime": "image/png",
                "path": str(Path(self.upload_tmp.name) / "g2.png")}
        Path(gen2["path"]).write_bytes(b"\x89PNG\r\n\x1a\n")
        with mock.patch.object(routes.image_gen, "generate_image", return_value=gen2):
            res = self.client.post(
                "/api/image/re-edit", headers=self.headers,
                json={"history_id": first["history_id"], "prompt": "darker background"},
            )
        self.assertEqual(res.status_code, 200, res.text)
        self.assertTrue(res.json()["ok"])
        hist = self.client.get("/api/image/history", headers=self.headers).json()["history"]
        parents = [h["params"].get("parent_history_id") for h in hist]
        self.assertIn(first["history_id"], parents)

    def test_user_isolation_and_delete_account(self) -> None:
        alice_session = self._create_session(self.headers)
        bob_headers = self._register("13800138000")

        hidden = self.client.get(f"/api/sessions/{alice_session}/messages", headers=bob_headers)
        self.assertEqual(hidden.status_code, 404)

        deleted = self.client.request(
            "DELETE",
            "/api/auth/me",
            headers=self.headers,
            json={"confirmation": "我确认注销账号"},
        )
        self.assertEqual(deleted.status_code, 200)
        after = self.client.get("/api/sessions", headers=self.headers)
        self.assertEqual(after.status_code, 401)


if __name__ == "__main__":
    unittest.main()
