from __future__ import annotations

from pathlib import Path

import pytest

from tech_desk.config import Settings, add_vendor_to_desk, list_desk_definitions


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


@pytest.fixture
def desk_config_copy(tmp_path: Path) -> Path:
    """A writable copy of the real desk config, so vendor-add tests don't mutate the repo file."""
    real_path = Path("config/tech_desks.yaml")
    copy_path = tmp_path / "tech_desks.yaml"
    copy_path.write_text(real_path.read_text(encoding="utf-8"), encoding="utf-8")
    return copy_path


def test_add_vendor_to_desk_appends_and_propagates(desk_config_copy: Path):
    before = list_desk_definitions(desk_config_copy)
    apps_before = next(d for d in before if d.id == "applications")
    assert "Snowflake" not in apps_before.key_vendors

    updated = add_vendor_to_desk("applications", "Snowflake", desk_config_copy)

    assert updated.id == "applications"
    assert "Snowflake" in updated.key_vendors
    # Re-parsing the file confirms the write actually landed on disk, and that
    # every other desk/field survived the edit untouched.
    after = list_desk_definitions(desk_config_copy)
    assert len(after) == len(before)
    apps_after = next(d for d in after if d.id == "applications")
    assert apps_after.key_vendors == apps_before.key_vendors + ["Snowflake"]
    for other in after:
        if other.id != "applications":
            assert other.model_dump() == next(d for d in before if d.id == other.id).model_dump()


def test_add_vendor_to_desk_rejects_duplicate(desk_config_copy: Path):
    add_vendor_to_desk("applications", "Snowflake", desk_config_copy)
    with pytest.raises(ValueError, match="already tracked"):
        add_vendor_to_desk("applications", "snowflake", desk_config_copy)  # case-insensitive dup


def test_add_vendor_to_desk_rejects_unknown_desk(desk_config_copy: Path):
    with pytest.raises(LookupError, match="Unknown desk"):
        add_vendor_to_desk("not-a-real-desk", "Snowflake", desk_config_copy)


def test_add_vendor_to_desk_rejects_blank_name(desk_config_copy: Path):
    with pytest.raises(ValueError, match="required"):
        add_vendor_to_desk("applications", "   ", desk_config_copy)
