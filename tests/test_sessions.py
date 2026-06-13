from __future__ import annotations

import unittest

from server import db, sessions


class SessionStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        sessions.reset_for_tests()

    def tearDown(self) -> None:
        sessions.reset_for_tests()

    def test_create_get_delete(self) -> None:
        session_id = sessions.create()
        self.assertTrue(sessions.exists(session_id))
        self.assertIsNotNone(sessions.get(session_id))

        self.assertTrue(sessions.delete(session_id))
        self.assertFalse(sessions.exists(session_id))
        self.assertIsNone(sessions.get(session_id))

    def test_persistence_rehydrates_from_db(self) -> None:
        session_id = sessions.create()
        conv = sessions.get(session_id)
        assert conv is not None
        # Persist a couple of turns directly via the db layer.
        db.add_message(session_id, "user", "hello")
        db.add_message(session_id, "assistant", "hi there")

        # Evict from the in-memory cache, then re-fetch — should rehydrate from SQLite.
        sessions._CACHE.clear()
        rehydrated = sessions.get(session_id)
        assert rehydrated is not None
        self.assertEqual(len(rehydrated.messages), 2)
        self.assertEqual(rehydrated.messages[0]["role"], "user")
        self.assertEqual(rehydrated.messages[0]["content"], "hello")

    def test_group_delete_cascades_sessions(self) -> None:
        group = db.create_group("Campaign A")
        sid = sessions.create(group_id=group["id"])
        self.assertTrue(sessions.exists(sid))

        db.delete_group(group["id"])
        self.assertIsNone(db.get_session(sid))


if __name__ == "__main__":
    unittest.main()
