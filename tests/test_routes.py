from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from server import sessions, uploads
from server.main import app


class RouteTests(unittest.TestCase):
    def setUp(self) -> None:
        sessions.reset_for_tests()
        os.environ["ANTHROPIC_API_KEY"] = "test-key"
        self.upload_tmp = tempfile.TemporaryDirectory()
        self.old_upload_dir = uploads.UPLOAD_DIR
        uploads.UPLOAD_DIR = Path(self.upload_tmp.name)
        self.client = TestClient(app)
        self.headers = self._register("alice")

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
                "username": account.title(),
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
                "account": "alice",
                "password": "password123",
                "username": "Alice",
                "real_name": "张三",
                "id_card": "11010519491231002X",
            },
        )
        self.assertEqual(duplicate.status_code, 409)

        me = self.client.get("/api/auth/me", headers=self.headers)
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.json()["user"]["account"], "alice")
        self.assertEqual(me.json()["user"]["id_card_masked"], "11010*********002X")

    def test_invalid_id_card_rejected(self) -> None:
        response = self.client.post(
            "/api/auth/register",
            json={
                "account": "badid",
                "password": "password123",
                "username": "Bad",
                "real_name": "李四",
                "id_card": "110105194912310021",
            },
        )
        self.assertEqual(response.status_code, 400)

    def test_business_routes_require_auth(self) -> None:
        response = self.client.get("/api/sessions")
        self.assertEqual(response.status_code, 401)

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

        user_id = db.get_user_by_account("alice")["id"]
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

    def test_user_isolation_and_delete_account(self) -> None:
        alice_session = self._create_session(self.headers)
        bob_headers = self._register("bob")

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
