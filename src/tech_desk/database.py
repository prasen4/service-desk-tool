from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
    event,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker

from tech_desk.config import get_settings
from tech_desk.models import RelevanceLevel, ResearchRunResult, UpdateCategory
from tech_desk.timeutils import now_utc


class Base(DeclarativeBase):
    pass


class ResearchRunORM(Base):
    __tablename__ = "research_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="running")
    period: Mapped[str] = mapped_column(String(16), default="daily")
    desks_processed: Mapped[int] = mapped_column(Integer, default=0)
    updates_found: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    updates: Mapped[list["UpdateORM"]] = relationship(back_populates="research_run")


class UpdateORM(Base):
    __tablename__ = "updates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    research_run_id: Mapped[int | None] = mapped_column(ForeignKey("research_runs.id"), nullable=True)
    desk_id: Mapped[str] = mapped_column(String(64), index=True)
    title: Mapped[str] = mapped_column(String(512))
    summary: Mapped[str] = mapped_column(Text)
    source_url: Mapped[str] = mapped_column(String(2048))
    source_name: Mapped[str] = mapped_column(String(256), default="")
    published_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    discovered_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, index=True)
    category: Mapped[str] = mapped_column(String(32), default=UpdateCategory.OTHER.value)
    relevance: Mapped[str] = mapped_column(String(16), default=RelevanceLevel.MEDIUM.value)
    tags_json: Mapped[str] = mapped_column(Text, default="[]")
    key_takeaways_json: Mapped[str] = mapped_column(Text, default="[]")
    stakeholder_impact: Mapped[str] = mapped_column(Text, default="")
    raw_snippet: Mapped[str] = mapped_column(Text, default="")
    vendor: Mapped[str] = mapped_column(String(128), default="", index=True)
    image_url: Mapped[str] = mapped_column(String(2048), default="")
    dedup_hash: Mapped[str] = mapped_column(String(64), index=True, unique=True)

    research_run: Mapped[ResearchRunORM | None] = relationship(back_populates="updates")


class ReportORM(Base):
    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    period: Mapped[str] = mapped_column(String(16), index=True)
    title: Mapped[str] = mapped_column(String(512))
    generated_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, index=True)
    period_start: Mapped[datetime] = mapped_column(DateTime)
    period_end: Mapped[datetime] = mapped_column(DateTime)
    executive_summary: Mapped[str] = mapped_column(Text, default="")
    content_json: Mapped[str] = mapped_column(Text)
    html_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    markdown_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    pdf_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)


class AppConfigORM(Base):
    __tablename__ = "app_config"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, onupdate=now_utc)


_engine = None
_SessionLocal = None


def get_engine():
    global _engine
    if _engine is None:
        settings = get_settings()
        url = settings.database_url
        connect_args: dict = {}
        if url.startswith("sqlite"):
            # Background jobs and the request threadpool share the engine, so
            # connections must be usable across threads. busy_timeout lets a
            # writer wait for a lock instead of failing with "database is locked".
            connect_args = {"check_same_thread": False, "timeout": 30}
        _engine = create_engine(
            url,
            echo=False,
            future=True,
            pool_pre_ping=True,
            connect_args=connect_args,
        )
        if url.startswith("sqlite"):
            _configure_sqlite(_engine)
    return _engine


def _configure_sqlite(engine) -> None:
    """Apply per-connection SQLite pragmas for durability and concurrency."""

    @event.listens_for(engine, "connect")
    def _set_pragmas(dbapi_conn, _record):  # pragma: no cover - driver callback
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


def get_session_factory():
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=get_engine(), autoflush=False, autocommit=False)
    return _SessionLocal


def init_db() -> None:
    engine = get_engine()
    Base.metadata.create_all(bind=engine)
    _migrate_schema(engine)


def _migrate_schema(engine) -> None:
    """Add columns introduced after initial release (SQLite-safe)."""
    from sqlalchemy import inspect, text

    inspector = inspect(engine)
    if "updates" not in inspector.get_table_names():
        return
    columns = {col["name"] for col in inspector.get_columns("updates")}
    migrations: list[tuple[str, str]] = [
        ("vendor", "ALTER TABLE updates ADD COLUMN vendor VARCHAR(128) DEFAULT ''"),
        ("image_url", "ALTER TABLE updates ADD COLUMN image_url VARCHAR(2048) DEFAULT ''"),
    ]
    for col_name, ddl in migrations:
        if col_name not in columns:
            with engine.begin() as conn:
                conn.execute(text(ddl))


def get_db_session():
    factory = get_session_factory()
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def tags_to_json(tags: list[str]) -> str:
    return json.dumps(tags)


def json_to_tags(raw: str) -> list[str]:
    try:
        return json.loads(raw) if raw else []
    except json.JSONDecodeError:
        return []


def record_token_sample(
    period: str,
    desk_count: int,
    input_tokens: int,
    output_tokens: int,
    *,
    alpha: float = 0.5,
) -> None:
    """Store measured per-desk token usage for a pipeline run (EMA-smoothed)."""
    if desk_count <= 0 or (input_tokens <= 0 and output_tokens <= 0):
        return
    in_per = input_tokens / desk_count
    out_per = output_tokens / desk_count

    factory = get_session_factory()
    session = factory()
    try:
        key = f"token_sample_{period}"
        existing = session.get(AppConfigORM, key)
        samples = 1
        if existing:
            try:
                prev = json.loads(existing.value)
                in_per = alpha * in_per + (1 - alpha) * prev.get("input_per_desk", in_per)
                out_per = alpha * out_per + (1 - alpha) * prev.get("output_per_desk", out_per)
                samples = int(prev.get("samples", 0)) + 1
            except (json.JSONDecodeError, TypeError):
                pass
        payload = {
            "input_per_desk": round(in_per),
            "output_per_desk": round(out_per),
            "desk_count": desk_count,
            "samples": samples,
            "at": now_utc().isoformat(),
        }
        session.merge(AppConfigORM(key=key, value=json.dumps(payload)))
        session.commit()
    except Exception:
        session.rollback()
    finally:
        session.close()


def get_token_sample(period: str) -> dict | None:
    """Return the latest measured per-desk token sample for a period, if any."""
    factory = get_session_factory()
    session = factory()
    try:
        row = session.get(AppConfigORM, f"token_sample_{period}")
        return json.loads(row.value) if row else None
    except (json.JSONDecodeError, TypeError):
        return None
    finally:
        session.close()


def all_token_samples() -> dict:
    """Return measured samples keyed by period."""
    return {p: s for p in ("daily", "weekly", "monthly") if (s := get_token_sample(p))}


def research_run_from_orm(orm: ResearchRunORM) -> ResearchRunResult:
    """Copy ORM fields into a plain object while the session is still open."""
    return ResearchRunResult(
        id=orm.id,
        status=orm.status,
        period=orm.period,
        desks_processed=orm.desks_processed,
        updates_found=orm.updates_found,
        error_message=orm.error_message,
        started_at=orm.started_at,
        completed_at=orm.completed_at,
    )
