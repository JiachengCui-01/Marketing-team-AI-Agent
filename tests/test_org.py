from __future__ import annotations

import unittest

from fastapi.testclient import TestClient

from server import db, sessions
from server.main import app

# Distinct valid mainland-China ID numbers (checksum-correct) for two users.
ID_ALICE = "11010519491231002X"
ID_BOB = "110101199001010023"


class OrgRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        sessions.reset_for_tests()
        self.client = TestClient(app)
        self.alice = self._register("alice@example.com", "Alice", ID_ALICE)
        self.bob = self._register("bob@example.com", "Bob", ID_BOB)

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

    def test_default_org_is_lazily_created(self) -> None:
        res = self.client.get("/api/org", headers=self.alice)
        self.assertEqual(res.status_code, 200, res.text)
        org = res.json()["org"]
        self.assertEqual(org["my_role"], "owner")
        self.assertTrue(org["invite_code"])
        self.assertIn("Alice", org["name"])

        # Idempotent: a second call returns the same org.
        again = self.client.get("/api/org", headers=self.alice).json()["org"]
        self.assertEqual(again["id"], org["id"])

    def test_join_by_invite_makes_members_visible_to_each_other(self) -> None:
        alice_org = self.client.get("/api/org", headers=self.alice).json()["org"]
        # Bob provisions his own default org first, then joins Alice's.
        self.client.get("/api/org", headers=self.bob)

        joined = self.client.post(
            "/api/org/join",
            headers=self.bob,
            json={"invite_code": alice_org["invite_code"]},
        )
        self.assertEqual(joined.status_code, 200, joined.text)
        self.assertEqual(joined.json()["org"]["id"], alice_org["id"])
        self.assertEqual(joined.json()["org"]["my_role"], "member")

        for headers in (self.alice, self.bob):
            members = self.client.get("/api/org/members", headers=headers)
            self.assertEqual(members.status_code, 200, members.text)
            body = members.json()
            self.assertEqual(body["org"]["id"], alice_org["id"])
            ids = {m["username"] for m in body["members"]}
            self.assertEqual(ids, {"Alice", "Bob"})
            roles = {m["username"]: m["role"] for m in body["members"]}
            self.assertEqual(roles["Alice"], "owner")
            self.assertEqual(roles["Bob"], "member")

    def test_invalid_invite_code_rejected(self) -> None:
        res = self.client.post(
            "/api/org/join", headers=self.bob, json={"invite_code": "NOPE1234"}
        )
        self.assertEqual(res.status_code, 404)

    def test_owner_cannot_leave_but_member_can(self) -> None:
        alice_org = self.client.get("/api/org", headers=self.alice).json()["org"]
        self.client.get("/api/org", headers=self.bob)
        self.client.post(
            "/api/org/join", headers=self.bob, json={"invite_code": alice_org["invite_code"]}
        )

        owner_leave = self.client.post("/api/org/leave", headers=self.alice)
        self.assertEqual(owner_leave.status_code, 400)

        member_leave = self.client.post("/api/org/leave", headers=self.bob)
        self.assertEqual(member_leave.status_code, 200, member_leave.text)
        # Bob falls back to his own re-provisioned default org.
        self.assertEqual(member_leave.json()["org"]["my_role"], "owner")

        # Alice's org no longer lists Bob.
        members = self.client.get("/api/org/members", headers=self.alice).json()["members"]
        self.assertEqual({m["username"] for m in members}, {"Alice"})

    def test_add_member_by_account(self) -> None:
        self.client.get("/api/org", headers=self.alice)
        self._register("carol@example.com", "Carol", "110101198001010037")

        added = self.client.post(
            "/api/org/members", headers=self.alice, json={"account": "carol@example.com"}
        )
        self.assertEqual(added.status_code, 200, added.text)
        members = self.client.get("/api/org/members", headers=self.alice).json()["members"]
        self.assertEqual({m["username"] for m in members}, {"Alice", "Carol"})

        dup = self.client.post(
            "/api/org/members", headers=self.alice, json={"account": "carol@example.com"}
        )
        self.assertEqual(dup.status_code, 409)

        missing = self.client.post(
            "/api/org/members", headers=self.alice, json={"account": "nobody@example.com"}
        )
        self.assertEqual(missing.status_code, 404)

    def test_member_removal_requires_privilege(self) -> None:
        alice_org = self.client.get("/api/org", headers=self.alice).json()["org"]
        self.client.get("/api/org", headers=self.bob)
        self.client.post(
            "/api/org/join", headers=self.bob, json={"invite_code": alice_org["invite_code"]}
        )
        members = self.client.get("/api/org/members", headers=self.alice).json()["members"]
        alice_id = next(m["id"] for m in members if m["username"] == "Alice")
        bob_id = next(m["id"] for m in members if m["username"] == "Bob")

        # A plain member cannot remove another member.
        denied = self.client.delete(f"/api/org/members/{alice_id}", headers=self.bob)
        self.assertEqual(denied.status_code, 403)

        # The owner cannot be removed at all.
        protect_owner = self.client.delete(f"/api/org/members/{alice_id}", headers=self.alice)
        self.assertEqual(protect_owner.status_code, 400)

        # The owner can remove a member.
        removed = self.client.delete(f"/api/org/members/{bob_id}", headers=self.alice)
        self.assertEqual(removed.status_code, 200, removed.text)
        members_after = self.client.get("/api/org/members", headers=self.alice).json()["members"]
        self.assertEqual({m["username"] for m in members_after}, {"Alice"})


if __name__ == "__main__":
    unittest.main()
