from __future__ import annotations

import re
import threading
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

    # Azure OpenAI (enterprise) only needs an API version in addition to the
    # fields above — the Azure resource endpoint is stored in OPENAI_BASE_URL
    # and the deployment name is stored in OPENAI_MODEL.
    azure_openai_api_version: str = Field(default="2024-10-21", validation_alias="AZURE_OPENAI_API_VERSION")

    tech_desk_data_dir: Path = Field(default=Path("./data"), validation_alias="TECH_DESK_DATA_DIR")
    tech_desk_host: str = Field(default="0.0.0.0", validation_alias="TECH_DESK_HOST")
    tech_desk_port: int = Field(default=8080, validation_alias="TECH_DESK_PORT")

    # Database. Leave DATABASE_URL empty to use the local SQLite file in the data
    # dir; set it to a PostgreSQL URL to support many concurrent writers/users.
    database_url_override: str = Field(default="", validation_alias="DATABASE_URL")
    db_pool_size: int = Field(default=5, validation_alias="DB_POOL_SIZE")
    db_max_overflow: int = Field(default=10, validation_alias="DB_MAX_OVERFLOW")
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
        if self.database_url_override.strip():
            return self.database_url_override.strip()
        db_path = self.tech_desk_data_dir / "tech_desk.db"
        return f"sqlite:///{db_path.resolve()}"

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def db_backend(self) -> str:
        return "sqlite" if self.is_sqlite else self.database_url.split(":", 1)[0].split("+", 1)[0]


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

_config_write_lock = threading.Lock()

_DESK_HEADER_RE = re.compile(r"^  - id:\s*(\S+)\s*$")
_KEY_VENDORS_RE = re.compile(r"^    key_vendors:\s*$")
_LIST_ITEM_RE = re.compile(r"^      - (.+)$")


def add_vendor_to_desk(
    desk_id: str,
    vendor_name: str,
    config_path: Path | None = None,
) -> TechDeskDefinition:
    """Append a vendor to a desk's ``key_vendors`` list in ``tech_desks.yaml``.

    This is the single source of truth consumed by research (vendor-targeted
    search queries), the Vendor News registry, and report generation — so
    adding a vendor here automatically propagates everywhere else without any
    further wiring, since none of those readers cache the parsed config.

    Edits the YAML in place with a small line-based patch (rather than a full
    ``yaml.safe_dump`` round-trip) so the file's existing comments, key order,
    and formatting are preserved exactly.
    """
    name = vendor_name.strip()
    if not name:
        raise ValueError("Vendor name is required.")
    if len(name) > 128:
        raise ValueError("Vendor name is too long (max 128 characters).")

    path = config_path or get_settings().config_path
    if not path.is_absolute():
        path = Path.cwd() / path

    with _config_write_lock:
        text = path.read_text(encoding="utf-8")
        lines = text.splitlines()

        desk_start = next(
            (i for i, line in enumerate(lines) if (m := _DESK_HEADER_RE.match(line)) and m.group(1) == desk_id),
            None,
        )
        if desk_start is None:
            all_desks = list_desk_definitions(config_path)
            valid = ", ".join(d.id for d in all_desks)
            raise LookupError(f"Unknown desk id: '{desk_id}'. Valid options: {valid}")

        desk_end = len(lines)
        for j in range(desk_start + 1, len(lines)):
            if _DESK_HEADER_RE.match(lines[j]) or re.match(r"^\S", lines[j]):
                desk_end = j
                break

        kv_line = next((j for j in range(desk_start, desk_end) if _KEY_VENDORS_RE.match(lines[j])), None)
        if kv_line is None:
            raise ValueError(f"Desk '{desk_id}' has no key_vendors list to add to.")

        insert_at = kv_line + 1
        existing: list[str] = []
        for j in range(kv_line + 1, desk_end):
            m = _LIST_ITEM_RE.match(lines[j])
            if not m:
                break
            existing.append(m.group(1).strip())
            insert_at = j + 1

        if any(v.lower() == name.lower() for v in existing):
            raise ValueError(f"'{name}' is already tracked on this desk.")

        lines.insert(insert_at, f"      - {name}")
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    return next(d for d in list_desk_definitions(config_path) if d.id == desk_id)
