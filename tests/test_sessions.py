from __future__ import annotations

import unittest

from server import db, sessions
from server import auth


class SessionStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        sessions.reset_for_tests()

    def tearDown(self) -> None:
        sessions.reset_for_tests()

    def create_user(self) -> str:
        user = db.create_user(
            account="alice",
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

    def test_group_delete_cascades_sessions(self) -> None:
        user_id = self.create_user()
        group = db.create_group(user_id, "Campaign A")
        sid = sessions.create(user_id, group_id=group["id"])
        self.assertTrue(sessions.exists(sid, user_id))

        db.delete_group(user_id, group["id"])
        self.assertIsNone(db.get_session(sid))


if __name__ == "__main__":
    unittest.main()
