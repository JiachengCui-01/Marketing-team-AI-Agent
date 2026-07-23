from __future__ import annotations

import asyncio
import unittest

from fastapi.testclient import TestClient

from server import im_hub, sessions
from server.main import app

ID_ALICE = "11010519491231002X"
ID_BOB = "110101199001010023"


class ImTests(unittest.TestCase):
    def setUp(self) -> None:
        sessions.reset_for_tests()
        im_hub.reset_for_tests()
        self.client = TestClient(app)
        self.alice, self.alice_id = self._register("alice@example.com", "Alice", ID_ALICE)
        self.bob, self.bob_id = self._register("bob@example.com", "Bob", ID_BOB)

    def tearDown(self) -> None:
        sessions.reset_for_tests()
        im_hub.reset_for_tests()

    def _register(self, account: str, username: str, id_card: str) -> tuple[dict[str, str], str]:
        res = self.client.post(
            "/api/auth/register",
            json={
                "account": account,
                "password": "password123",
                "username": username,
                "real_name": "张三",
                "id_card": id_card,
            },
        )
        self.assertEqual(res.status_code, 200, res.text)
        body = res.json()
        return {"Authorization": f"Bearer {body['token']}"}, body["user"]["id"]

    def _create_direct(self) -> str:
        res = self.client.post(
            "/api/conversations", headers=self.alice, json={"type": "direct", "peer_id": self.bob_id}
        )
        self.assertEqual(res.status_code, 200, res.text)
        return res.json()["conversation"]["id"]

    def test_direct_dedupe(self) -> None:
        first = self._create_direct()
        second = self._create_direct()
        self.assertEqual(first, second)

    def test_send_updates_unread_and_history(self) -> None:
        cid = self._create_direct()
        sent = self.client.post(
            f"/api/conversations/{cid}/messages", headers=self.alice, json={"content": "hi bob"}
        )
        self.assertEqual(sent.status_code, 200, sent.text)

        convs = self.client.get("/api/conversations", headers=self.bob).json()["conversations"]
        self.assertEqual(len(convs), 1)
        self.assertEqual(convs[0]["unread"], 1)
        self.assertEqual(convs[0]["last_message"]["content"], "hi bob")
        self.assertEqual(convs[0]["peer"]["username"], "Alice")

        # Sender's own view is already read.
        alice_convs = self.client.get("/api/conversations", headers=self.alice).json()["conversations"]
        self.assertEqual(alice_convs[0]["unread"], 0)

        history = self.client.get(f"/api/conversations/{cid}/messages", headers=self.bob).json()["messages"]
        self.assertEqual([m["content"] for m in history], ["hi bob"])

        self.client.post(f"/api/conversations/{cid}/read", headers=self.bob)
        after = self.client.get("/api/conversations", headers=self.bob).json()["conversations"]
        self.assertEqual(after[0]["unread"], 0)

    def test_group_conversation(self) -> None:
        res = self.client.post(
            "/api/conversations",
            headers=self.alice,
            json={"type": "group", "title": "Team", "member_ids": [self.bob_id]},
        )
        self.assertEqual(res.status_code, 200, res.text)
        conv = res.json()["conversation"]
        self.assertEqual(conv["type"], "group")
        self.assertEqual(conv["title"], "Team")
        self.assertEqual(conv["member_count"], 2)

        cid = conv["id"]
        self.client.post(f"/api/conversations/{cid}/messages", headers=self.alice, json={"content": "hello team"})
        groups = self.client.get("/api/conversations?type=group", headers=self.bob).json()["conversations"]
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["unread"], 1)

    def test_group_invite_and_member_listing(self) -> None:
        res = self.client.post(
            "/api/conversations",
            headers=self.alice,
            json={"type": "group", "title": "Team", "member_ids": [self.bob_id]},
        )
        cid = res.json()["conversation"]["id"]

        members = self.client.get(f"/api/conversations/{cid}/members", headers=self.alice).json()["members"]
        self.assertEqual({m["username"] for m in members}, {"Alice", "Bob"})
        self.assertEqual(next(m["role"] for m in members if m["username"] == "Alice"), "owner")

        # Invite Carol by account.
        self._register("carol@example.com", "Carol", "110101198001010037")
        invited = self.client.post(
            f"/api/conversations/{cid}/members", headers=self.alice, json={"account": "carol@example.com"}
        )
        self.assertEqual(invited.status_code, 200, invited.text)
        self.assertEqual({m["username"] for m in invited.json()["members"]}, {"Alice", "Bob", "Carol"})

    def test_cannot_invite_to_direct(self) -> None:
        cid = self._create_direct()
        _, carol_id = self._register("carol@example.com", "Carol", "110101198001010037")
        res = self.client.post(
            f"/api/conversations/{cid}/members", headers=self.alice, json={"member_ids": [carol_id]}
        )
        self.assertEqual(res.status_code, 400)

    def test_non_member_cannot_read(self) -> None:
        cid = self._create_direct()
        carol_headers, _ = self._register("carol@example.com", "Carol", "110101198001010037")
        denied = self.client.get(f"/api/conversations/{cid}/messages", headers=carol_headers)
        self.assertEqual(denied.status_code, 404)

    def test_file_message_share_and_download_authz(self) -> None:
        cid = self._create_direct()
        up = self.client.post(
            "/api/upload",
            headers=self.alice,
            files={"file": ("hello.png", b"\x89PNG\r\n\x1a\nfake-bytes", "image/png")},
        )
        self.assertEqual(up.status_code, 200, up.text)
        file_id = up.json()["file_id"]

        sent = self.client.post(
            f"/api/conversations/{cid}/messages",
            headers=self.alice,
            json={"file": {"file_id": file_id}},
        )
        self.assertEqual(sent.status_code, 200, sent.text)
        self.assertEqual(sent.json()["message"]["kind"], "file")

        # A member (Bob) can download the shared file even though he did not upload it.
        dl = self.client.get(f"/api/conversations/{cid}/files/{file_id}/download", headers=self.bob)
        self.assertEqual(dl.status_code, 200, dl.text)

        # A non-member (Carol) cannot.
        carol_headers, _ = self._register("carol@example.com", "Carol", "110101198001010037")
        denied = self.client.get(
            f"/api/conversations/{cid}/files/{file_id}/download", headers=carol_headers
        )
        self.assertEqual(denied.status_code, 404)

    def test_read_receipt_updates_peer_last_read(self) -> None:
        cid = self._create_direct()
        self.client.post(f"/api/conversations/{cid}/messages", headers=self.alice, json={"content": "hi"})
        before = self.client.get("/api/conversations", headers=self.alice).json()["conversations"][0]
        self.assertIn("peer_last_read_at", before)

        self.client.post(f"/api/conversations/{cid}/read", headers=self.bob)
        after = self.client.get("/api/conversations", headers=self.alice).json()["conversations"][0]
        self.assertIsNotNone(after["peer_last_read_at"])
        self.assertGreater(after["peer_last_read_at"], 0)

    def test_hub_delivers_to_subscriber(self) -> None:
        async def scenario() -> dict:
            queue = im_hub.subscribe(self.bob_id)
            try:
                im_hub.publish(self.bob_id, {"event": "im_message", "payload": {"content": "ping"}})
                return await asyncio.wait_for(queue.get(), timeout=1.0)
            finally:
                im_hub.unsubscribe(self.bob_id, queue)

        event = asyncio.run(scenario())
        self.assertEqual(event["event"], "im_message")
        self.assertEqual(event["payload"]["content"], "ping")
        self.assertEqual(im_hub.subscriber_count(self.bob_id), 0)


if __name__ == "__main__":
    unittest.main()
