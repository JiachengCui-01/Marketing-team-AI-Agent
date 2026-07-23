from __future__ import annotations

import unittest

from fastapi.testclient import TestClient

from server import sessions
from server.main import app

ID_ALICE = "11010519491231002X"
ID_BOB = "110101199001010023"


class ContactRouteTests(unittest.TestCase):
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

    def test_manual_external_contact_crud(self) -> None:
        created = self.client.post(
            "/api/contacts/external",
            headers=self.alice,
            json={"name": "王五", "email": "wang@vendor.com", "company": "Vendor Co"},
        )
        self.assertEqual(created.status_code, 200, created.text)
        self.assertEqual(created.json()["mode"], "manual")
        cid = created.json()["contact"]["id"]

        listed = self.client.get("/api/contacts/external", headers=self.alice).json()["contacts"]
        self.assertEqual(len(listed), 1)
        self.assertFalse(listed[0]["starred"])

        starred = self.client.patch(
            f"/api/contacts/external/{cid}", headers=self.alice, json={"starred": True}
        )
        self.assertEqual(starred.status_code, 200, starred.text)
        self.assertTrue(starred.json()["contact"]["starred"])

        deleted = self.client.delete(f"/api/contacts/external/{cid}", headers=self.alice)
        self.assertEqual(deleted.status_code, 200, deleted.text)
        self.assertEqual(self.client.get("/api/contacts/external", headers=self.alice).json()["contacts"], [])

    def test_add_registered_user_creates_request_then_accept(self) -> None:
        res = self.client.post(
            "/api/contacts/external", headers=self.alice, json={"account": "bob@example.com"}
        )
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(res.json()["mode"], "request")

        incoming = self.client.get("/api/contacts/requests", headers=self.bob).json()["incoming"]
        self.assertEqual(len(incoming), 1)
        self.assertEqual(incoming[0]["username"], "Alice")
        request_id = incoming[0]["id"]

        # Alice sees it as outgoing.
        outgoing = self.client.get("/api/contacts/requests", headers=self.alice).json()["outgoing"]
        self.assertEqual(len(outgoing), 1)

        accepted = self.client.post(f"/api/contacts/requests/{request_id}/accept", headers=self.bob)
        self.assertEqual(accepted.status_code, 200, accepted.text)

        # Reciprocal contacts exist on both sides, linked to the counterpart user.
        alice_contacts = self.client.get("/api/contacts/external", headers=self.alice).json()["contacts"]
        bob_contacts = self.client.get("/api/contacts/external", headers=self.bob).json()["contacts"]
        self.assertEqual(len(alice_contacts), 1)
        self.assertEqual(len(bob_contacts), 1)
        self.assertEqual(alice_contacts[0]["name"], "Bob")
        self.assertEqual(bob_contacts[0]["name"], "Alice")
        self.assertIsNotNone(alice_contacts[0]["contact_user_id"])

        # Request no longer pending for either party.
        self.assertEqual(self.client.get("/api/contacts/requests", headers=self.bob).json()["incoming"], [])

    def test_reject_request(self) -> None:
        self.client.post(
            "/api/contacts/external", headers=self.alice, json={"account": "bob@example.com"}
        )
        request_id = self.client.get("/api/contacts/requests", headers=self.bob).json()["incoming"][0]["id"]
        rejected = self.client.post(f"/api/contacts/requests/{request_id}/reject", headers=self.bob)
        self.assertEqual(rejected.status_code, 200, rejected.text)
        # No contacts created.
        self.assertEqual(self.client.get("/api/contacts/external", headers=self.alice).json()["contacts"], [])
        self.assertEqual(self.client.get("/api/contacts/requests", headers=self.bob).json()["incoming"], [])

    def test_cannot_add_self_or_duplicate(self) -> None:
        me = self.client.post(
            "/api/contacts/external", headers=self.alice, json={"account": "alice@example.com"}
        )
        self.assertEqual(me.status_code, 400)

        # Establish a link, then a second add should be rejected as duplicate.
        self.client.post("/api/contacts/external", headers=self.alice, json={"account": "bob@example.com"})
        rid = self.client.get("/api/contacts/requests", headers=self.bob).json()["incoming"][0]["id"]
        self.client.post(f"/api/contacts/requests/{rid}/accept", headers=self.bob)
        dup = self.client.post(
            "/api/contacts/external", headers=self.alice, json={"account": "bob@example.com"}
        )
        self.assertEqual(dup.status_code, 409)

    def test_star_org_member_appears_in_starred(self) -> None:
        # Alice and Bob share Alice's org.
        alice_org = self.client.get("/api/org", headers=self.alice).json()["org"]
        self.client.get("/api/org", headers=self.bob)
        self.client.post("/api/org/join", headers=self.bob, json={"invite_code": alice_org["invite_code"]})
        members = self.client.get("/api/org/members", headers=self.alice).json()["members"]
        bob_id = next(m["id"] for m in members if m["username"] == "Bob")

        starred = self.client.post(
            "/api/contacts/star", headers=self.alice, json={"member_user_id": bob_id}
        )
        self.assertEqual(starred.status_code, 200, starred.text)
        body = self.client.get("/api/contacts/starred", headers=self.alice).json()
        self.assertEqual({m["username"] for m in body["members"]}, {"Bob"})

        self.client.delete(f"/api/contacts/star/{bob_id}", headers=self.alice)
        body_after = self.client.get("/api/contacts/starred", headers=self.alice).json()
        self.assertEqual(body_after["members"], [])


if __name__ == "__main__":
    unittest.main()
