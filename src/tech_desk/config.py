from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from tech_desk.models import TechDeskDefinition


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    llm_provider: str = Field(default="openai", validation_alias="LLM_PROVIDER")
    openai_api_key: str = Field(default="", validation_alias="OPENAI_API_KEY")
    openai_base_url: str = Field(default="https://api.openai.com/v1", validation_alias="OPENAI_BASE_URL")
    openai_model: str = Field(default="gpt-4o", validation_alias="OPENAI_MODEL")

    tech_desk_data_dir: Path = Field(default=Path("./data"), validation_alias="TECH_DESK_DATA_DIR")
    tech_desk_host: str = Field(default="0.0.0.0", validation_alias="TECH_DESK_HOST")
    tech_desk_port: int = Field(default=8080, validation_alias="TECH_DESK_PORT")
    tech_desk_secret_key: str = Field(default="dev-secret-change-me", validation_alias="TECH_DESK_SECRET_KEY")
    env: str = Field(default="development", validation_alias="ENV")
    log_level: str = Field(default="INFO", validation_alias="LOG_LEVEL")

    # Performance: skip slow og:image + DDGS fetches during research; fetch at report time only
    image_fetch_enabled: bool = Field(default=True, validation_alias="IMAGE_FETCH_ENABLED")
    image_fetch_during_research: bool = Field(default=False, validation_alias="IMAGE_FETCH_DURING_RESEARCH")
    image_fetch_timeout: float = Field(default=3.0, validation_alias="IMAGE_FETCH_TIMEOUT")

    scheduler_enabled: bool = Field(default=False, validation_alias="SCHEDULER_ENABLED")
    cors_origins: str = Field(default="*", validation_alias="CORS_ORIGINS")

    research_max_results_per_query: int = Field(default=8, validation_alias="RESEARCH_MAX_RESULTS_PER_QUERY")
    research_lookback_days: int = Field(default=30, validation_alias="RESEARCH_LOOKBACK_DAYS")
    priority_desk_depth_multiplier: int = Field(default=2, validation_alias="PRIORITY_DESK_DEPTH_MULTIPLIER")

    sharepoint_site_url: str | None = Field(default=None, validation_alias="SHAREPOINT_SITE_URL")
    sharepoint_client_id: str | None = Field(default=None, validation_alias="SHAREPOINT_CLIENT_ID")
    sharepoint_client_secret: str | None = Field(default=None, validation_alias="SHAREPOINT_CLIENT_SECRET")
    sharepoint_tenant_id: str | None = Field(default=None, validation_alias="SHAREPOINT_TENANT_ID")

    config_path: Path = Field(default=Path("config/tech_desks.yaml"))

    def ensure_directories(self) -> None:
        self.tech_desk_data_dir.mkdir(parents=True, exist_ok=True)
        (self.tech_desk_data_dir / "reports").mkdir(parents=True, exist_ok=True)
        (self.tech_desk_data_dir / "exports").mkdir(parents=True, exist_ok=True)
        (self.tech_desk_data_dir / "logs").mkdir(parents=True, exist_ok=True)

    @property
    def is_production(self) -> bool:
        return self.env.lower() in ("production", "prod")

    @property
    def cors_origin_list(self) -> list[str]:
        if self.cors_origins.strip() == "*":
            return ["*"]
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def database_url(self) -> str:
        db_path = self.tech_desk_data_dir / "tech_desk.db"
        return f"sqlite:///{db_path.resolve()}"


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_directories()
    return settings


def load_desk_config(config_path: Path | None = None) -> dict:
    path = config_path or get_settings().config_path
    if not path.is_absolute():
        # Resolve relative to project root (cwd when running CLI/server)
        path = Path.cwd() / path
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def list_desk_definitions(config_path: Path | None = None) -> list[TechDeskDefinition]:
    config = load_desk_config(config_path)
    return [TechDeskDefinition.model_validate(d) for d in config.get("desks", [])]


def resolve_desks(
    desk_keys: list[str] | None = None,
    config_path: Path | None = None,
) -> list[TechDeskDefinition]:
    """Resolve desk id, code (e.g. APPS), or partial name to desk definitions."""
    all_desks = list_desk_definitions(config_path)
    if not desk_keys:
        return all_desks

    resolved: list[TechDeskDefinition] = []
    seen: set[str] = set()
    unknown: list[str] = []

    for key in desk_keys:
        token = key.strip()
        if not token:
            continue
        lower = token.lower()
        match = next(
            (
                d
                for d in all_desks
                if d.id.lower() == lower
                or d.code.lower() == lower
                or d.name.lower() == lower
                or lower in d.name.lower()
            ),
            None,
        )
        if match is None:
            unknown.append(token)
            continue
        if match.id not in seen:
            seen.add(match.id)
            resolved.append(match)

    if unknown:
        valid = ", ".join(f"{d.code} ({d.id})" for d in all_desks)
        raise ValueError(f"Unknown desk(s): {', '.join(unknown)}. Valid options: {valid}")

    return resolved


ReportPeriod = Literal["daily", "weekly", "monthly"]
