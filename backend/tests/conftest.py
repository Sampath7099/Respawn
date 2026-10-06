"""Integration tests write orders and events. Never let them touch the real database."""
import os

import pytest


def pytest_collection_modifyitems(config, items):
    dsn = os.environ.get("RESPAWN_DSN", "postgresql://respawn:respawn@localhost:5433/respawn")
    if dsn.rstrip("/").endswith("/respawn") and not os.environ.get("RESPAWN_TESTS_ON_MAIN_DB"):
        skip = pytest.mark.skip(reason="integration tests need a test database: set RESPAWN_DSN (CI uses the fixture DB)")
        for item in items:
            if "test_api" in item.nodeid:
                item.add_marker(skip)
