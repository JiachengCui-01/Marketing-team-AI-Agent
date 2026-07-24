from __future__ import annotations

import unittest

from fastapi.testclient import TestClient

from server import db, sessions
from server.main import app

ID_ALICE = "11010519491231002X"
ID_BOB = "110101199001010023"
ID_CAROL = "110101198001010037"


class ApprovalRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        sessions.reset_for_tests()
        self.client = TestClient(app)
        self.alice = self._register("alice@example.com", "Alice", ID_ALICE)
        self.bob = self._register("bob@example.com", "Bob", ID_BOB)
        # Alice owns an org; Bob joins it so Alice's requests route to Bob.
        alice_org = self.client.get("/api/org", headers=self.alice).json()["org"]
        self.client.get("/api/org", headers=self.bob)
        self.client.post(
            "/api/org/join", headers=self.bob, json={"invite_code": alice_org["invite_code"]}
        )

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

    def test_submit_and_approve_flow(self) -> None:
        created = self.client.post(
            "/api/approvals",
            headers=self.alice,
            json={"type": "leave", "title": "年假申请（3 天）", "fields": {"days": 3}},
        )
        self.assertEqual(created.status_code, 200, created.text)
        appr = created.json()["approval"]
        self.assertEqual(appr["status"], "pending")
        self.assertEqual(appr["applicant_name"], "Alice")
        self.assertEqual(appr["steps"][0]["approver_name"], "Bob")

        # Bob sees it as pending; Alice sees it under "mine".
        pending = self.client.get("/api/approvals?scope=pending", headers=self.bob).json()
        self.assertEqual(len(pending["approvals"]), 1)
        mine = self.client.get("/api/approvals?scope=mine", headers=self.alice).json()
        self.assertEqual(len(mine["approvals"]), 1)

        acted = self.client.post(
            f"/api/approvals/{appr['id']}/act",
            headers=self.bob,
            json={"action": "approved", "comment": "同意"},
        )
        self.assertEqual(acted.status_code, 200, acted.text)
        self.assertEqual(acted.json()["approval"]["status"], "approved")

        # It moved out of Bob's pending queue and into Alice's approved history.
        pending_after = self.client.get("/api/approvals?scope=pending", headers=self.bob).json()
        self.assertEqual(len(pending_after["approvals"]), 0)
        mine_after = self.client.get("/api/approvals?scope=mine", headers=self.alice).json()
        self.assertEqual(mine_after["approvals"][0]["status"], "approved")

    def test_reject_flow(self) -> None:
        appr = self.client.post(
            "/api/approvals",
            headers=self.alice,
            json={"type": "expense", "title": "报销 100 元", "fields": {"amount": 100}},
        ).json()["approval"]
        acted = self.client.post(
            f"/api/approvals/{appr['id']}/act",
            headers=self.bob,
            json={"action": "rejected"},
        )
        self.assertEqual(acted.json()["approval"]["status"], "rejected")

    def test_non_approver_cannot_act(self) -> None:
        appr = self.client.post(
            "/api/approvals",
            headers=self.alice,
            json={"type": "general", "title": "用章申请", "fields": {}},
        ).json()["approval"]
        # Alice is the applicant, not the approver.
        denied = self.client.post(
            f"/api/approvals/{appr['id']}/act", headers=self.alice, json={"action": "approved"}
        )
        self.assertEqual(denied.status_code, 400)

    def test_empty_title_rejected(self) -> None:
        res = self.client.post(
            "/api/approvals", headers=self.alice, json={"type": "leave", "title": "  "}
        )
        self.assertEqual(res.status_code, 400)

    def test_solo_org_has_no_approver(self) -> None:
        carol = self._register("carol@example.com", "Carol", ID_CAROL)
        self.client.get("/api/org", headers=carol)  # solo default org
        res = self.client.post(
            "/api/approvals", headers=carol, json={"type": "leave", "title": "请假"}
        )
        self.assertEqual(res.status_code, 400)

    def test_modify_and_withdraw_own_pending(self) -> None:
        appr = self.client.post(
            "/api/approvals",
            headers=self.alice,
            json={"type": "leave", "title": "年假 1 天", "fields": {"days": 1}},
        ).json()["approval"]

        # applicant modifies own pending application
        edited = self.client.patch(
            f"/api/approvals/{appr['id']}", headers=self.alice, json={"title": "年假 2 天"}
        )
        self.assertEqual(edited.status_code, 200, edited.text)
        self.assertEqual(edited.json()["approval"]["title"], "年假 2 天")

        # the approver cannot modify someone else's application
        self.assertEqual(
            self.client.patch(
                f"/api/approvals/{appr['id']}", headers=self.bob, json={"title": "x"}
            ).status_code,
            400,
        )

        # applicant withdraws
        wd = self.client.post(f"/api/approvals/{appr['id']}/withdraw", headers=self.alice)
        self.assertEqual(wd.json()["approval"]["status"], "withdrawn")
        # once withdrawn it is no longer pending for the approver
        self.assertEqual(
            len(self.client.get("/api/approvals?scope=pending", headers=self.bob).json()["approvals"]),
            0,
        )

    def test_cannot_view_unrelated_approval(self) -> None:
        carol = self._register("carol@example.com", "Carol", ID_CAROL)
        self.client.get("/api/org", headers=carol)
        appr = self.client.post(
            "/api/approvals",
            headers=self.alice,
            json={"type": "leave", "title": "私密申请", "fields": {}},
        ).json()["approval"]
        # Carol is neither applicant nor approver → cannot see it.
        self.assertEqual(
            self.client.get(f"/api/approvals/{appr['id']}", headers=carol).status_code, 403
        )

    def test_bad_action_rejected(self) -> None:
        appr = self.client.post(
            "/api/approvals",
            headers=self.alice,
            json={"type": "leave", "title": "请假 1 天", "fields": {"days": 1}},
        ).json()["approval"]
        res = self.client.post(
            f"/api/approvals/{appr['id']}/act", headers=self.bob, json={"action": "maybe"}
        )
        self.assertEqual(res.status_code, 400)


if __name__ == "__main__":
    unittest.main()
