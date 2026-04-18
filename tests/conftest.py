"""Fixtures for queue system tests."""

import os
import sys
import pytest
import sqlite3
from contextlib import contextmanager

# Ensure project root is importable when pytest is invoked directly.
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from core.database import DatabaseManager
from core.queue_manager import QueueManager
from core.validators import validate_user_id

# Test constants
TEST_USER_ID = "test_user_12345"
ADMIN_USER_ID = "admin_xxxxx"


@pytest.fixture
def db_path(tmp_path):
    """Create a temporary SQLite DB path for tests."""
    return str(tmp_path / "test_queue.db")


@pytest.fixture
def db_manager(db_path):
    """Create a DatabaseManager instance with test DB."""
    return DatabaseManager(db_path)


@pytest.fixture
def queue_manager(db_path):
    """Create a QueueManager instance with test DB."""
    return QueueManager(DatabaseManager(db_path))


@pytest.fixture
def valid_user_id():
    """Return a valid test user ID."""
    return TEST_USER_ID


@pytest.fixture
def admin_user_id():
    """Return a valid admin user ID."""
    return ADMIN_USER_ID


@pytest.fixture
def admin_ids():
    """Return list of admin IDs for auth tests."""
    return [ADMIN_USER_ID, "another_admin"]
