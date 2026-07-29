from __future__ import annotations

from pathlib import Path

from tech_desk.config import Settings, list_desk_definitions


def _settings(**overrides) -> Settings:
    # Fields use validation_alias (uppercase env names); pass by alias and skip
    # the real .env so tests are hermetic.
    return Settings(_env_file=None, **overrides)


def test_cors_origin_list_wildcard():
    assert _settings(CORS_ORIGINS="*").cors_origin_list == ["*"]


def test_cors_origin_list_parses_and_trims():
    parsed = _settings(CORS_ORIGINS="https://a.com, https://b.com ,").cors_origin_list
    assert parsed == ["https://a.com", "https://b.com"]


def test_is_production_flag():
    assert _settings(ENV="production").is_production is True
    assert _settings(ENV="PROD").is_production is True
    assert _settings(ENV="development").is_production is False


def test_database_url_points_into_data_dir(tmp_path: Path):
    settings = _settings(TECH_DESK_DATA_DIR=tmp_path)
    url = settings.database_url
    assert url.startswith("sqlite:///")
    assert "tech_desk.db" in url


def test_ensure_directories_creates_tree(tmp_path: Path):
    settings = _settings(TECH_DESK_DATA_DIR=tmp_path / "nested")
    settings.ensure_directories()
    assert (tmp_path / "nested" / "reports").is_dir()
    assert (tmp_path / "nested" / "logs").is_dir()


def test_database_url_defaults_to_sqlite(tmp_path: Path):
    settings = _settings(TECH_DESK_DATA_DIR=tmp_path)
    assert settings.is_sqlite is True
    assert settings.db_backend == "sqlite"
    assert settings.database_url.startswith("sqlite:///")


def test_database_url_override_takes_precedence():
    url = "postgresql+psycopg://u:p@localhost:5432/techdesk"
    settings = _settings(DATABASE_URL=url)
    assert settings.database_url == url
    assert settings.is_sqlite is False
    assert settings.db_backend == "postgresql"


def test_blank_database_url_falls_back_to_sqlite(tmp_path: Path):
    settings = _settings(TECH_DESK_DATA_DIR=tmp_path, DATABASE_URL="   ")
    assert settings.is_sqlite is True


def test_desk_definitions_have_required_fields():
    desks = list_desk_definitions()
    assert len(desks) == 5
    for desk in desks:
        assert desk.id and desk.code and desk.name
        assert desk.search_queries
        assert desk.key_vendors
