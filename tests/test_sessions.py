from __future__ import annotations

import unittest

from server import db, sessions
from server import auth
from server import memory


class SessionStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        sessions.reset_for_tests()

    def tearDown(self) -> None:
        sessions.reset_for_tests()

    def create_user(self) -> str:
        user = db.create_user(
            account="alice@example.com",
            password_hash=auth.hash_password("password123"),
            username="Alice",
            real_name="张三",
            id_card="11010519491231002X",
        )
        return user["id"]

    def test_create_get_delete(self) -> None:
        user_id = self.create_user()
        session_id = sessions.create(user_id)
        self.assertTrue(sessions.exists(session_id, user_id))
        self.assertIsNotNone(sessions.get(session_id, user_id))

        self.assertTrue(sessions.delete(session_id, user_id))
        self.assertFalse(sessions.exists(session_id, user_id))
        self.assertIsNone(sessions.get(session_id, user_id))

    def test_persistence_rehydrates_from_db(self) -> None:
        user_id = self.create_user()
        session_id = sessions.create(user_id)
        conv = sessions.get(session_id, user_id)
        assert conv is not None
        # Persist a couple of turns directly via the db layer.
        db.add_message(session_id, "user", "hello")
        db.add_message(session_id, "assistant", "hi there")

        # Evict from the in-memory cache, then re-fetch — should rehydrate from SQLite.
        sessions._CACHE.clear()
        rehydrated = sessions.get(session_id, user_id)
        assert rehydrated is not None
        self.assertEqual(len(rehydrated.messages), 2)
        self.assertEqual(rehydrated.messages[0]["role"], "user")
        self.assertEqual(rehydrated.messages[0]["content"], "hello")

    def test_prepare_for_turn_compresses_old_messages(self) -> None:
        user_id = self.create_user()
        session_id = sessions.create(user_id)
        for idx in range(18):
            db.add_message(session_id, "user", f"write campaign copy round {idx}")
            db.add_message(session_id, "assistant", f"draft output round {idx}")

        conv = sessions.prepare_for_turn(session_id, user_id)
        assert conv is not None
        serialized = "\n".join(str(m["content"]) for m in conv.messages)
        self.assertIn("Conversation summary", serialized)
        self.assertIn("round 17", serialized)
        self.assertLess(len(conv.messages), 36)

    def test_prepare_for_turn_injects_marketing_profile(self) -> None:
        user_id = self.create_user()
        session_id = sessions.create(user_id)
        db.upsert_user_marketing_memory(
            user_id,
            {
                "channels": ["Little Red Book"],
                "audiences": ["Consumer lifestyle audiences"],
                "deliverables": ["Marketing copy"],
            },
        )

        conv = sessions.prepare_for_turn(session_id, user_id)
        assert conv is not None
        self.assertIn("Long-term enterprise marketing profile", conv.messages[0]["content"])
        self.assertIn("Little Red Book", conv.messages[0]["content"])

    def test_long_term_memory_requires_repeated_evidence(self) -> None:
        user_id = self.create_user()
        session_id = sessions.create(user_id)
        prompt = "write XHS marketing copy for a SaaS product"

        memory.update_long_term_marketing_memory(user_id, prompt)
        memory.update_long_term_marketing_memory(user_id, prompt)
        self.assertIsNone(db.get_user_marketing_memory(user_id))

        memory.update_long_term_marketing_memory(user_id, prompt)
        stored = db.get_user_marketing_memory(user_id)
        self.assertIsNotNone(stored)
        assert stored is not None
        self.assertIn("Little Red Book", stored["profile"]["channels"])

        conv = sessions.prepare_for_turn(session_id, user_id)
        assert conv is not None
        self.assertIn("Long-term enterprise marketing profile", conv.messages[0]["content"])
        self.assertIn("Little Red Book", conv.messages[0]["content"])

    def test_long_term_memory_extracts_structured_profile_fields(self) -> None:
        user_id = self.create_user()
        prompt = (
            "我的职位是增长负责人。所属行业是消费电子。公司是星环科技。主要产品是AI手机。"
            "目标客户是科技尝鲜人群。常用渠道是小红书。语气偏好是真实种草。"
            "报告格式偏好是结论先行。KPI是曝光和转化率。其他偏好是少用夸张表达。"
        )

        for _ in range(memory.LONG_TERM_EVIDENCE_THRESHOLD):
            memory.update_long_term_marketing_memory(user_id, prompt)

        stored = db.get_user_marketing_memory(user_id)
        self.assertIsNotNone(stored)
        assert stored is not None
        profile = stored["profile"]
        self.assertIn("增长负责人", profile["role_title"])
        self.assertIn("消费电子", profile["industry"])
        self.assertIn("星环科技", profile["company_brand"])
        self.assertIn("AI手机", profile["products"])
        self.assertIn("科技尝鲜人群", profile["target_customers"])
        self.assertIn("小红书", profile["channels"])
        self.assertIn("真实种草", profile["tone_preferences"])
        self.assertIn("结论先行", profile["report_format_preferences"])
        self.assertIn("曝光和转化率", profile["kpi_data_preferences"])
        self.assertIn("少用夸张表达", profile["other_preferences"])

    def test_memory_block_keeps_current_request_priority(self) -> None:
        user_id = self.create_user()
        session_id = sessions.create(user_id)
        db.upsert_user_marketing_memory(user_id, {"channels": ["Little Red Book"]})

        conv = sessions.prepare_for_turn(session_id, user_id)
        assert conv is not None
        self.assertIn("the current request takes priority", conv.messages[0]["content"])

    def test_group_delete_cascades_sessions(self) -> None:
        user_id = self.create_user()
        group = db.create_group(user_id, "Campaign A")
        sid = sessions.create(user_id, group_id=group["id"])
        self.assertTrue(sessions.exists(sid, user_id))

        db.delete_group(user_id, group["id"])
        self.assertIsNone(db.get_session(sid))


if __name__ == "__main__":
    unittest.main()
