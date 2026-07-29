from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.pool import QueuePool

from tech_desk.config import Settings, get_settings
from tech_desk.database import get_engine, reset_engine


def test_sqlite_engine_is_writable(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("TECH_DESK_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    get_settings.cache_clear()
    reset_engine()

    engine = get_engine()
    assert engine.dialect.name == "sqlite"
    with engine.begin() as conn:
        assert conn.exec_driver_sql("SELECT 1").scalar() == 1

    reset_engine()
    get_settings.cache_clear()


def test_postgres_url_builds_pooled_engine_without_connecting(monkeypatch, tmp_path: Path):
    """Engine construction for Postgres must not require a live server."""
    pytest.importorskip("psycopg")

    url = "postgresql+psycopg://techdesk:techdesk@localhost:5432/techdesk"
    monkeypatch.setenv("TECH_DESK_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("DATABASE_URL", url)
    get_settings.cache_clear()
    reset_engine()

    settings = get_settings()
    assert settings.is_sqlite is False
    assert settings.db_backend == "postgresql"

    engine = get_engine()
    assert engine.dialect.name == "postgresql"
    assert isinstance(engine.pool, QueuePool)

    reset_engine()
    get_settings.cache_clear()
    monkeypatch.delenv("DATABASE_URL", raising=False)


def test_settings_is_sqlite_helpers():
    sqlite = Settings(_env_file=None, TECH_DESK_DATA_DIR="/tmp/td")
    assert sqlite.is_sqlite and sqlite.db_backend == "sqlite"

    pg = Settings(
        _env_file=None,
        DATABASE_URL="postgresql+psycopg://u:p@h/db",
    )
    assert not pg.is_sqlite and pg.db_backend == "postgresql"
