from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

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
from tech_desk.models import PositionPaperResult, RelevanceLevel, ResearchRunResult, UpdateCategory, VendorStatus
from tech_desk.timeutils import now_utc

logger = logging.getLogger(__name__)


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
    custom_instructions: Mapped[str | None] = mapped_column(Text, nullable=True)

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
    who_is_affected_first: Mapped[str] = mapped_column(String(256), default="")
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
    custom_instructions: Mapped[str | None] = mapped_column(Text, nullable=True)


class AppConfigORM(Base):
    __tablename__ = "app_config"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, onupdate=now_utc)


class VendorORM(Base):
    """Canonical vendor CRM profile — relationship pipeline, notes, and attachments."""

    __tablename__ = "vendors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(32), default=VendorStatus.IDENTIFIED.value)
    owner: Mapped[str] = mapped_column(String(128), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, onupdate=now_utc)

    notes: Mapped[list["VendorNoteORM"]] = relationship(
        back_populates="vendor", cascade="all, delete-orphan", order_by="VendorNoteORM.created_at.desc()"
    )
    status_events: Mapped[list["VendorStatusEventORM"]] = relationship(
        back_populates="vendor", cascade="all, delete-orphan", order_by="VendorStatusEventORM.created_at.desc()"
    )
    attachments: Mapped[list["VendorAttachmentORM"]] = relationship(
        back_populates="vendor", cascade="all, delete-orphan", order_by="VendorAttachmentORM.uploaded_at.desc()"
    )


class VendorNoteORM(Base):
    """Analyst-authored note on a vendor (plaintext/markdown)."""

    __tablename__ = "vendor_notes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    vendor_id: Mapped[int] = mapped_column(ForeignKey("vendors.id", ondelete="CASCADE"), index=True)
    body: Mapped[str] = mapped_column(Text)
    author: Mapped[str] = mapped_column(String(128), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, index=True)

    vendor: Mapped["VendorORM"] = relationship(back_populates="notes")
    attachments: Mapped[list["VendorAttachmentORM"]] = relationship(back_populates="note")


class VendorAttachmentORM(Base):
    """A file uploaded alongside a vendor note (pitch deck, POC results, etc.)."""

    __tablename__ = "vendor_attachments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    vendor_id: Mapped[int] = mapped_column(ForeignKey("vendors.id", ondelete="CASCADE"), index=True)
    note_id: Mapped[int | None] = mapped_column(
        ForeignKey("vendor_notes.id", ondelete="SET NULL"), nullable=True, index=True
    )
    original_filename: Mapped[str] = mapped_column(String(256))
    stored_filename: Mapped[str] = mapped_column(String(256))
    content_type: Mapped[str] = mapped_column(String(128), default="application/octet-stream")
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, index=True)

    vendor: Mapped["VendorORM"] = relationship(back_populates="attachments")
    note: Mapped["VendorNoteORM | None"] = relationship(back_populates="attachments")


class VendorStatusEventORM(Base):
    """A timestamped transition in a vendor's pipeline stage."""

    __tablename__ = "vendor_status_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    vendor_id: Mapped[int] = mapped_column(ForeignKey("vendors.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(32))
    note: Mapped[str] = mapped_column(Text, default="")
    changed_by: Mapped[str] = mapped_column(String(128), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, index=True)

    vendor: Mapped["VendorORM"] = relationship(back_populates="status_events")


class PositionPaperORM(Base):
    """A generated per-vendor Cotiviti Position Paper (.docx) — durable record."""

    __tablename__ = "position_papers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    vendor: Mapped[str] = mapped_column(String(128), index=True)
    status: Mapped[str] = mapped_column(String(16), default="running")
    custom_prompt: Mapped[str] = mapped_column(Text, default="")
    research_brief_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    docx_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, index=True)
    generated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class JobORM(Base):
    """Durable record of a background job — survives process restarts."""

    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    job_type: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    message: Mapped[str] = mapped_column(String(512), default="Queued")
    progress: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    result_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


_engine = None
_SessionLocal = None


def reset_engine() -> None:
    """Drop the cached engine/session factory (used by tests and config reloads)."""
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionLocal = None


def get_engine():
    global _engine
    if _engine is None:
        settings = get_settings()
        url = settings.database_url
        if settings.is_sqlite:
            # Background jobs and the request threadpool share the engine, so
            # connections must be usable across threads. busy_timeout lets a
            # writer wait for a lock instead of failing with "database is locked".
            _engine = create_engine(
                url,
                echo=False,
                future=True,
                pool_pre_ping=True,
                connect_args={"check_same_thread": False, "timeout": 30},
            )
            _configure_sqlite(_engine)
        else:
            # Server databases (e.g. PostgreSQL) handle many concurrent
            # writers; use a connection pool sized for the workload.
            _engine = create_engine(
                url,
                echo=False,
                future=True,
                pool_pre_ping=True,
                pool_size=settings.db_pool_size,
                max_overflow=settings.db_max_overflow,
                pool_recycle=1800,
            )
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


def _migrations_dir() -> Path:
    return Path(__file__).resolve().parent / "migrations"


def _alembic_config():
    from alembic.config import Config

    cfg = Config()
    cfg.set_main_option("script_location", str(_migrations_dir()))
    return cfg


def init_db() -> None:
    """Create/upgrade the schema via Alembic migrations.

    Fresh databases run every migration from scratch. Databases created by an
    older release (before Alembic was introduced, via ``Base.metadata.create_all``)
    are detected and stamped to the baseline revision so only the *new*
    migrations run against them — no data loss, no duplicate-table errors.
    """
    from alembic import command
    from sqlalchemy import inspect

    engine = get_engine()
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    pre_alembic_install = bool(existing_tables) and "alembic_version" not in existing_tables

    cfg = _alembic_config()
    with engine.begin() as conn:
        cfg.attributes["connection"] = conn
        if pre_alembic_install:
            logger.info("Existing pre-Alembic database detected — stamping baseline revision")
            command.stamp(cfg, "0001_baseline")
        command.upgrade(cfg, "head")


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
    vendors_added: list[str] = []
    if orm.metadata_json:
        try:
            vendors_added = json.loads(orm.metadata_json).get("vendors_added", [])
        except (json.JSONDecodeError, TypeError, AttributeError):
            vendors_added = []
    return ResearchRunResult(
        id=orm.id,
        status=orm.status,
        period=orm.period,
        desks_processed=orm.desks_processed,
        updates_found=orm.updates_found,
        vendors_added=vendors_added,
        error_message=orm.error_message,
        started_at=orm.started_at,
        completed_at=orm.completed_at,
    )


def position_paper_from_orm(orm: PositionPaperORM) -> PositionPaperResult:
    """Copy ORM fields into a plain object while the session is still open."""
    return PositionPaperResult(
        id=orm.id,
        vendor=orm.vendor,
        status=orm.status,
        custom_prompt=orm.custom_prompt,
        docx_path=orm.docx_path,
        generated_at=orm.generated_at,
        error_message=orm.error_message,
    )
