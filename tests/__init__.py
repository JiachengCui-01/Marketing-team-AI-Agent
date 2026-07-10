"""Test package bootstrap.

CRITICAL: point the database at a throwaway temp file BEFORE any test imports
``server.db``. ``db.reset_for_tests()`` deletes the database between tests, so it
must never resolve to the developer's real ``tmp/marketing_agent.db``. Importing
this package (which happens for any ``tests.*`` module) sets the env var first, so
``server.db.DB_PATH`` — read at import time — points at an isolated test DB.
"""
from __future__ import annotations

import os
import tempfile

os.environ["MARKETING_AGENT_DB_PATH"] = os.path.join(
    tempfile.gettempdir(), "marketing_agent_TEST_ONLY.db"
)
