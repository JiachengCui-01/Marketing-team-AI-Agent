from __future__ import annotations

import unittest

from fastapi.testclient import TestClient

from marketing_agent.oa.tools import OA_TOOLS, build_oa_handlers
from server import db, sessions
from server.main import app

ID_ALICE = "11010519491231002X"
ID_BOB = "110101199001010023"


class OaHandlerTests(unittest.TestCase):
    """The OA tool handlers must work without any model API key (offline degrade)."""

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
        response = self.client.post(
            "/api/auth/register",
            json={
                "account": account,
                "password": "password123",
                "username": username,
                "real_name": "张三",
                "id_card": id_card,
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        return {"Authorization": f"Bearer {response.json()['token']}"}

    def test_tool_schemas_present(self) -> None:
        names = {t["name"] for t in OA_TOOLS}
        # Approvals were removed from the workspace; the write tools that remain are
        # task and calendar drafts, and both stay human-in-the-loop.
        self.assertEqual(
            names,
            {
                "draft_task",
                "query_tasks",
                "draft_event",
                "query_calendar",
                "search_knowledge_base",
            },
        )

    def test_draft_task_emits_event_and_does_not_persist(self) -> None:
        events: list[tuple[str, dict]] = []
        handlers = build_oa_handlers(on_event=lambda e, p: events.append((e, p)), user_id=self.alice_id)
        result = handlers["draft_task"]({"title": "跟进餐桌打样", "priority": "high"})
        self.assertTrue(any(e == "oa_draft" for e, _ in events))
        draft = next(p for e, p in events if e == "oa_draft")
        self.assertEqual(draft["kind"], "task")
        self.assertEqual(draft["title"], "跟进餐桌打样")
        self.assertIn("确认", result)
        # Nothing was written until the user confirms the card.
        self.assertEqual(db.list_tasks(self.alice_id, scope="all"), [])

    def test_read_tools_present_and_functional(self) -> None:
        handlers = build_oa_handlers(user_id=self.alice_id)
        # Phase 2-4 tools are now implemented (no longer stubs).
        self.assertIn("query_tasks", handlers)
        self.assertIn("query_calendar", handlers)
        self.assertIn("search_knowledge_base", handlers)
        self.assertIn("没有", handlers["query_tasks"]({}))
        self.assertIn("没有", handlers["query_calendar"]({}))

    def test_calendar_update_draft_carries_existing_event_id(self) -> None:
        created = self.client.post(
            "/api/calendar",
            headers=self.alice,
            json={"title": "新品选品会议", "start": "2099-01-02T08:00"},
        ).json()["event"]
        events: list[tuple[str, dict]] = []
        handlers = build_oa_handlers(
            on_event=lambda event, payload: events.append((event, payload)),
            user_id=self.alice_id,
        )

        listed = handlers["query_calendar"]({})
        self.assertIn(created["id"], listed)
        result = handlers["draft_event"](
            {
                "event_id": created["id"],
                "title": "新品选品会议",
                "start": "2099-01-02T08:00",
                "location": "会议室 701",
            }
        )
        draft = next(payload for event, payload in events if event == "oa_draft")
        self.assertEqual(draft["event_id"], created["id"])
        self.assertEqual(draft["location"], "会议室 701")
        self.assertNotIn("attendees", draft)
        self.assertIn("确认更新", result)

    def test_oa_stream_requires_auth_and_prompt(self) -> None:
        self.assertEqual(self.client.get("/api/oa/stream?prompt=hi").status_code, 401)
        self.assertEqual(
            self.client.get("/api/oa/stream?prompt=%20", headers=self.alice).status_code, 400
        )


if __name__ == "__main__":
    unittest.main()
