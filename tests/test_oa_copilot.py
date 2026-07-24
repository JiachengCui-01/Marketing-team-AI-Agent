from __future__ import annotations

import unittest

from fastapi.testclient import TestClient

from marketing_agent.oa.tools import OA_TOOLS, build_oa_handlers
from server import db, sessions
from server.main import app

ID_ALICE = "11010519491231002X"
ID_BOB = "110101199001010023"


class OaHandlerTests(unittest.TestCase):
    """The OA tool handlers must work without any Anthropic API key (offline degrade)."""

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
        self.assertIn("draft_approval", names)
        self.assertIn("query_approvals", names)

    def test_draft_approval_emits_event_and_does_not_persist(self) -> None:
        events: list[tuple[str, dict]] = []
        handlers = build_oa_handlers(on_event=lambda e, p: events.append((e, p)), user_id=self.alice_id)
        result = handlers["draft_approval"](
            {"type": "leave", "title": "年假 3 天", "fields": {"days": 3}}
        )
        self.assertTrue(any(e == "oa_draft" for e, _ in events))
        draft = next(p for e, p in events if e == "oa_draft")
        self.assertEqual(draft["type"], "leave")
        self.assertEqual(draft["fields"]["days"], 3)
        self.assertIn("确认", result)
        # Nothing was written to the approvals table.
        self.assertEqual(db.list_approvals_created_by(self.alice_id), [])

    def test_query_approvals_reads_db(self) -> None:
        handlers = build_oa_handlers(user_id=self.alice_id)
        self.assertIn("暂无", handlers["query_approvals"]({"scope": "mine"}))
        self.client.post(
            "/api/approvals",
            headers=self.alice,
            json={"type": "leave", "title": "年假 2 天", "fields": {"days": 2}},
        )
        listed = handlers["query_approvals"]({"scope": "mine"})
        self.assertIn("年假 2 天", listed)

    def test_read_tools_present_and_functional(self) -> None:
        handlers = build_oa_handlers(user_id=self.alice_id)
        # Phase 2-4 tools are now implemented (no longer stubs).
        self.assertIn("query_tasks", handlers)
        self.assertIn("query_calendar", handlers)
        self.assertIn("search_knowledge_base", handlers)
        self.assertIn("没有", handlers["query_tasks"]({}))
        self.assertIn("没有", handlers["query_calendar"]({}))

    def test_oa_stream_requires_auth_and_prompt(self) -> None:
        self.assertEqual(self.client.get("/api/oa/stream?prompt=hi").status_code, 401)
        self.assertEqual(
            self.client.get("/api/oa/stream?prompt=%20", headers=self.alice).status_code, 400
        )


if __name__ == "__main__":
    unittest.main()
