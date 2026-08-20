from __future__ import annotations


def test_check_database_ok():
    from tech_desk import diagnostics

    result = diagnostics.check_database()
    assert result["ok"] is True


def test_check_migrations_ok():
    """The test DB is created via init_db() (conftest), so it should always
    be stamped at the latest migration head."""
    from tech_desk import diagnostics

    result = diagnostics.check_migrations()
    assert result["ok"] is True
    assert result["current_revisions"] == result["head_revisions"]


def test_check_api_key_true_with_dummy_key():
    from tech_desk import diagnostics

    result = diagnostics.check_api_key()
    assert result["ok"] is True  # conftest sets a dummy OPENAI_API_KEY


def test_check_desk_config_ok():
    from tech_desk import diagnostics

    result = diagnostics.check_desk_config()
    assert result["ok"] is True
    assert result["desks"] == 5
    assert result["desks_missing_search_queries"] == []


def test_check_search_backend_defaults_to_ddg_when_unset(monkeypatch):
    """Uses a stubbed Settings object rather than relying on env vars, since
    pydantic-settings reads the repo's real .env file directly (independent
    of process env vars) and a developer machine may have SEARXNG_URL set."""
    from types import SimpleNamespace

    from tech_desk import diagnostics

    monkeypatch.setattr(
        "tech_desk.config.get_settings",
        lambda: SimpleNamespace(searxng_url="", search_backend="auto"),
    )

    result = diagnostics.check_search_backend()

    assert result["ok"] is True
    assert result["configured"] is False


def test_check_search_backend_forced_ddg_skips_searxng(monkeypatch):
    """SEARCH_BACKEND=ddg should report ok regardless of SEARXNG_URL, since
    SearXNG is never queried in this mode."""
    from types import SimpleNamespace

    from tech_desk import diagnostics

    monkeypatch.setattr(
        "tech_desk.config.get_settings",
        lambda: SimpleNamespace(searxng_url="http://localhost:8888", search_backend="ddg"),
    )

    result = diagnostics.check_search_backend()

    assert result == {"ok": True, "backend": "ddg", "note": "SearXNG not used (SEARCH_BACKEND=ddg)"}


def test_check_search_backend_forced_searxng_without_url_fails(monkeypatch):
    """SEARCH_BACKEND=searxng with no SEARXNG_URL is a blocking failure —
    there's no DuckDuckGo fallback in forced mode."""
    from types import SimpleNamespace

    from tech_desk import diagnostics

    monkeypatch.setattr(
        "tech_desk.config.get_settings",
        lambda: SimpleNamespace(searxng_url="", search_backend="searxng"),
    )

    result = diagnostics.check_search_backend()

    assert result["ok"] is False
    assert result["configured"] is False


def test_check_search_backend_forced_searxng_unreachable_fails(monkeypatch):
    """SEARCH_BACKEND=searxng with an unreachable instance is blocking too."""
    from types import SimpleNamespace

    from tech_desk import diagnostics

    monkeypatch.setattr(
        "tech_desk.config.get_settings",
        lambda: SimpleNamespace(searxng_url="http://localhost:1", search_backend="searxng"),
    )

    result = diagnostics.check_search_backend()

    assert result["ok"] is False
    assert result["reachable"] is False


def test_run_all_checks_ready_status():
    from tech_desk import diagnostics

    result = diagnostics.run_all_checks()
    assert result["status"] == "ready"
    assert set(result["checks"]) == {
        "database",
        "migrations",
        "disk_writable",
        "api_key_configured",
        "desk_config",
        "search_backend",
    }
