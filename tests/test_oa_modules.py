from __future__ import annotations

import unittest

from fastapi.testclient import TestClient

from marketing_agent.oa.tools import build_oa_handlers
from server import sessions
from server.main import app

ID_ALICE = "11010519491231002X"
ID_BOB = "110101199001010023"


class OaModulesTests(unittest.TestCase):
    """Phase 2-4: tasks, calendar, knowledge base."""

    def setUp(self) -> None:
        sessions.reset_for_tests()
        self.client = TestClient(app)
        self.alice = self._register("alice@example.com", "Alice", ID_ALICE)
        self.bob = self._register("bob@example.com", "Bob", ID_BOB)
        alice_org = self.client.get("/api/org", headers=self.alice).json()["org"]
        self.client.get("/api/org", headers=self.bob)
        self.client.post(
            "/api/org/join", headers=self.bob, json={"invite_code": alice_org["invite_code"]}
        )
        members = self.client.get("/api/org/members", headers=self.alice).json()["members"]
        self.alice_id = next(m["id"] for m in members if m["username"] == "Alice")

    def tearDown(self) -> None:
        sessions.reset_for_tests()

    def _register(self, account: str, username: str, id_card: str) -> dict[str, str]:
        r = self.client.post(
            "/api/auth/register",
            json={
                "account": account,
                "password": "password123",
                "username": username,
                "real_name": "张三",
                "id_card": id_card,
            },
        )
        self.assertEqual(r.status_code, 200, r.text)
        return {"Authorization": f"Bearer {r.json()['token']}"}

    # ----- tasks -----

    def test_task_assign_and_complete(self) -> None:
        created = self.client.post(
            "/api/tasks",
            headers=self.alice,
            json={"title": "写周报", "detail": "本周总结", "assignee_name": "Bob"},
        )
        self.assertEqual(created.status_code, 200, created.text)
        task = created.json()["task"]
        self.assertEqual(task["assignee_name"], "Bob")

        assigned = self.client.get("/api/tasks?scope=assigned", headers=self.bob).json()["tasks"]
        self.assertEqual(len(assigned), 1)

        done = self.client.patch(
            f"/api/tasks/{task['id']}", headers=self.bob, json={"status": "done"}
        )
        self.assertEqual(done.json()["task"]["status"], "done")

    def test_task_defaults_to_self_and_bad_status(self) -> None:
        task = self.client.post(
            "/api/tasks", headers=self.alice, json={"title": "整理资料"}
        ).json()["task"]
        self.assertEqual(task["assignee_name"], "Alice")
        bad = self.client.patch(f"/api/tasks/{task['id']}", headers=self.alice, json={"status": "x"})
        self.assertEqual(bad.status_code, 400)

    def test_task_requires_title(self) -> None:
        self.assertEqual(
            self.client.post("/api/tasks", headers=self.alice, json={"title": " "}).status_code, 400
        )

    # ----- calendar -----

    def test_calendar_create_and_list(self) -> None:
        created = self.client.post(
            "/api/calendar",
            headers=self.alice,
            json={"title": "周会", "start": "2099-01-01T14:00", "end": "2099-01-01T15:00",
                  "location": "会议室A", "attendees": ["Bob"]},
        )
        self.assertEqual(created.status_code, 200, created.text)
        self.assertEqual(created.json()["event"]["attendees"], ["Bob"])
        events = self.client.get("/api/calendar", headers=self.alice).json()["events"]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["title"], "周会")

    def test_calendar_bad_start(self) -> None:
        r = self.client.post(
            "/api/calendar", headers=self.alice, json={"title": "会", "start": "not-a-date"}
        )
        self.assertEqual(r.status_code, 400)

    # ----- knowledge base -----

    def test_kb_add_search_delete(self) -> None:
        created = self.client.post(
            "/api/kb/documents",
            headers=self.alice,
            json={"title": "报销制度", "text": "公司报销需在 30 天内提交发票，交通费上限 500 元。"},
        )
        self.assertEqual(created.status_code, 200, created.text)
        doc_id = created.json()["document"]["id"]

        docs = self.client.get("/api/kb/documents", headers=self.alice).json()["documents"]
        self.assertEqual(len(docs), 1)

        found = self.client.post(
            "/api/kb/search", headers=self.alice, json={"q": "报销 发票"}
        ).json()["results"]
        self.assertTrue(len(found) >= 1)
        self.assertEqual(found[0]["title"], "报销制度")

        # Uploads go to the user's PERSONAL KB, so an org peer cannot see Alice's doc.
        found_bob = self.client.post(
            "/api/kb/search", headers=self.bob, json={"q": "报销"}
        ).json()["results"]
        self.assertEqual(len(found_bob), 0)

        self.assertEqual(
            self.client.delete(f"/api/kb/documents/{doc_id}", headers=self.alice).status_code, 200
        )
        self.assertEqual(
            len(self.client.get("/api/kb/documents", headers=self.alice).json()["documents"]), 0
        )

    def test_kb_empty_rejected(self) -> None:
        self.assertEqual(
            self.client.post("/api/kb/documents", headers=self.alice, json={"text": "  "}).status_code,
            400,
        )

    # ----- copilot handlers (offline) -----

    def test_copilot_handlers_offline(self) -> None:
        events: list[tuple[str, dict]] = []
        h = build_oa_handlers(on_event=lambda e, p: events.append((e, p)), user_id=self.alice_id)
        # draft_task emits a task draft, persists nothing
        h["draft_task"]({"title": "跟进客户", "assignee_name": "Bob"})
        self.assertTrue(any(e == "oa_draft" and p["kind"] == "task" for e, p in events))
        # draft_event emits a calendar draft
        h["draft_event"]({"title": "评审会", "start": "2099-01-01T10:00"})
        self.assertTrue(any(e == "oa_draft" and p["kind"] == "calendar" for e, p in events))
        # query handlers read the DB
        self.assertIn("没有", h["query_tasks"]({}))
        self.assertIn("没有", h["query_calendar"]({}))
        # kb search with no docs
        self.assertIn("没有", h["search_knowledge_base"]({"query": "报销"}))


if __name__ == "__main__":
    unittest.main()
