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

    def test_upload_rejects_non_csv_extension(self) -> None:
        response = self.client.post(
            "/api/upload",
            files={"file": ("campaign.txt", b"a,b\n1,2\n", "text/plain")},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "Only .csv files are supported.")

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


if __name__ == "__main__":
    unittest.main()
