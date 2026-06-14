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

    def tearDown(self) -> None:
        uploads.UPLOAD_DIR = self.old_upload_dir
        self.upload_tmp.cleanup()
        sessions.reset_for_tests()

    def test_health(self) -> None:
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    def test_session_create_delete(self) -> None:
        created = self.client.post("/api/sessions")
        self.assertEqual(created.status_code, 200)
        session_id = created.json()["session_id"]
        self.assertTrue(sessions.exists(session_id))

        deleted = self.client.delete(f"/api/sessions/{session_id}")
        self.assertEqual(deleted.status_code, 200)
        self.assertFalse(sessions.exists(session_id))

    def test_upload_csv_success(self) -> None:
        response = self.client.post(
            "/api/upload",
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
            files={"file": ("empty.csv", b"", "text/csv")},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "Empty file.")

    def test_upload_rejects_unsupported_extension(self) -> None:
        response = self.client.post(
            "/api/upload",
            files={"file": ("notes.txt", b"a,b\n1,2\n", "text/plain")},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("Unsupported file type", response.json()["detail"])

    def test_upload_accepts_pdf(self) -> None:
        response = self.client.post(
            "/api/upload",
            files={"file": ("brief.pdf", b"%PDF-1.4 minimal", "application/pdf")},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["mime"], "application/pdf")

    def test_upload_rejects_oversized_csv(self) -> None:
        oversized = b"a" * (uploads.MAX_UPLOAD_BYTES + 1)
        response = self.client.post(
            "/api/upload",
            files={"file": ("large.csv", oversized, "text/csv")},
        )
        self.assertEqual(response.status_code, 413)

    def test_stream_rejects_invalid_csv_id(self) -> None:
        created = self.client.post("/api/sessions")
        session_id = created.json()["session_id"]

        response = self.client.get(
            f"/api/sessions/{session_id}/stream",
            params={"prompt": "Analyze this", "csv_id": "not-a-real-id"},
        )
        self.assertEqual(response.status_code, 404)

    def test_session_messages_include_artifacts(self) -> None:
        created = self.client.post("/api/sessions")
        session_id = created.json()["session_id"]
        db_path = Path(self.upload_tmp.name) / "artifact.pdf"
        db_path.write_bytes(b"%PDF-1.4")
        from server import db

        db.add_message(session_id, "user", "make a pdf")
        db.add_message(session_id, "assistant", "PDF generated.")
        rec = db.add_artifact(
            session_id=session_id,
            kind="pdf",
            filename="Campaign.pdf",
            mime="application/pdf",
            path=str(db_path),
        )

        response = self.client.get(f"/api/sessions/{session_id}/messages")
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
            created = self.client.post("/api/sessions")
            session_id = created.json()["session_id"]

            with self.client.stream(
                "GET",
                f"/api/sessions/{session_id}/stream",
                params={"prompt": "write a post"},
            ) as response:
                self.assertEqual(response.status_code, 200)
                body = response.read().decode("utf-8")

            self.assertIn('"event": "error"', body)
            messages = self.client.get(f"/api/sessions/{session_id}/messages").json()["messages"]
            self.assertEqual(messages[-1]["role"], "assistant")
            self.assertEqual(messages[-1]["content"], "**Error:** model unavailable")
        finally:
            streaming.run_orchestrator = old_run_orchestrator


if __name__ == "__main__":
    unittest.main()
