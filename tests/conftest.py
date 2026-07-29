"""Shared pytest fixtures and test isolation.

Every test runs against a throwaway data directory and a dummy API key so the
suite never touches the developer's real database, reports, or credentials.
The environment is set before any ``tech_desk`` module is imported so the
cached settings pick up the test values.
"""

from __future__ import annotations

import atexit
import os
import shutil
import tempfile

_TEST_DATA_DIR = tempfile.mkdtemp(prefix="tech-desk-tests-")
os.environ.setdefault("TECH_DESK_DATA_DIR", _TEST_DATA_DIR)
os.environ.setdefault("OPENAI_API_KEY", "sk-test-dummy-key-000000000000")
os.environ.setdefault("ENV", "test")
os.environ.setdefault("SCHEDULER_ENABLED", "false")


@atexit.register
def _cleanup_test_data_dir() -> None:
    shutil.rmtree(_TEST_DATA_DIR, ignore_errors=True)


import pytest  # noqa: E402  (import after env is configured)

from tech_desk.database import get_session_factory, init_db  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _init_database() -> None:
    """Create the schema once for the whole test session."""
    init_db()


@pytest.fixture
def db_session():
    """A database session that is always closed after the test."""
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client():
    """FastAPI test client with application lifespan started."""
    from fastapi.testclient import TestClient

    from tech_desk.api.main import app

    with TestClient(app) as test_client:
        yield test_client
