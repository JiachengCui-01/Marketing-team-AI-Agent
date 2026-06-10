from __future__ import annotations

import unittest

from server import sessions


class SessionStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        sessions.reset_for_tests()
        self.old_ttl = sessions.SESSION_TTL_SECONDS
        self.old_max = sessions.MAX_SESSIONS

    def tearDown(self) -> None:
        sessions.SESSION_TTL_SECONDS = self.old_ttl
        sessions.MAX_SESSIONS = self.old_max
        sessions.reset_for_tests()

    def test_ttl_prunes_expired_session(self) -> None:
        session_id = sessions.create()
        self.assertTrue(sessions.exists(session_id))

        sessions.SESSION_TTL_SECONDS = -1
        self.assertIsNone(sessions.get(session_id))
        self.assertFalse(sessions.exists(session_id))

    def test_capacity_prunes_oldest_session(self) -> None:
        sessions.MAX_SESSIONS = 2
        first = sessions.create()
        second = sessions.create()
        third = sessions.create()

        self.assertFalse(sessions.exists(first))
        self.assertTrue(sessions.exists(second))
        self.assertTrue(sessions.exists(third))


if __name__ == "__main__":
    unittest.main()
