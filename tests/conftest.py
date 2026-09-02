"""Suite-wide guard: no test may reach a live, metered vendor.

``server.main`` calls ``load_dotenv()`` at import, so once a real
``SELLERSPRITE_SECRET_KEY`` sits in ``.env`` an ordinary ``pytest`` run would let
the research and analytics agents open a live MCP session and spend vendor
credits — the suite is supposed to stay entirely offline.

The key is therefore cleared for the session. The SellerSprite tests set it back
themselves and fake the transport, so coverage is unaffected. Set
``MARKETING_AGENT_TEST_LIVE_VENDOR=1`` to opt into real calls deliberately.
"""
from __future__ import annotations

import os

import pytest

from marketing_agent.tools import sellersprite


@pytest.fixture(autouse=True, scope="session")
def _keep_vendor_calls_offline():
    live = os.environ.get("MARKETING_AGENT_TEST_LIVE_VENDOR", "").strip().lower()
    if live in {"1", "true", "yes", "on"}:
        yield
        return
    # Popped after collection, which is when load_dotenv() has already run.
    previous = os.environ.pop("SELLERSPRITE_SECRET_KEY", None)
    sellersprite.reset_for_tests()
    try:
        yield
    finally:
        if previous is not None:
            os.environ["SELLERSPRITE_SECRET_KEY"] = previous
        sellersprite.reset_for_tests()
