"""Baseline schema — research_runs, updates, reports, app_config.

This mirrors the schema produced by the pre-Alembic release (including the
``vendor`` and ``image_url`` columns on ``updates`` that were previously added
by ad hoc ``ALTER TABLE`` checks in ``database._migrate_schema``). Existing
installations are stamped directly to this revision without re-running it
(see ``tech_desk.database.init_db``); fresh installations run it from empty.

Revision ID: 0001_baseline
Revises:
Create Date: 2026-07-29

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0001_baseline"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "research_runs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("period", sa.String(length=16), nullable=False),
        sa.Column("desks_processed", sa.Integer(), nullable=False),
        sa.Column("updates_found", sa.Integer(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("metadata_json", sa.Text(), nullable=True),
    )

    op.create_table(
        "updates",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("research_run_id", sa.Integer(), sa.ForeignKey("research_runs.id"), nullable=True),
        sa.Column("desk_id", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("source_url", sa.String(length=2048), nullable=False),
        sa.Column("source_name", sa.String(length=256), nullable=False, server_default=""),
        sa.Column("published_date", sa.DateTime(), nullable=True),
        sa.Column("discovered_at", sa.DateTime(), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("relevance", sa.String(length=16), nullable=False),
        sa.Column("tags_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("key_takeaways_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("stakeholder_impact", sa.Text(), nullable=False, server_default=""),
        sa.Column("raw_snippet", sa.Text(), nullable=False, server_default=""),
        sa.Column("vendor", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("image_url", sa.String(length=2048), nullable=False, server_default=""),
        sa.Column("dedup_hash", sa.String(length=64), nullable=False),
    )
    op.create_index("ix_updates_desk_id", "updates", ["desk_id"])
    op.create_index("ix_updates_discovered_at", "updates", ["discovered_at"])
    op.create_index("ix_updates_vendor", "updates", ["vendor"])
    op.create_index("ix_updates_dedup_hash", "updates", ["dedup_hash"], unique=True)

    op.create_table(
        "reports",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("period", sa.String(length=16), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("generated_at", sa.DateTime(), nullable=False),
        sa.Column("period_start", sa.DateTime(), nullable=False),
        sa.Column("period_end", sa.DateTime(), nullable=False),
        sa.Column("executive_summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("content_json", sa.Text(), nullable=False),
        sa.Column("html_path", sa.String(length=1024), nullable=True),
        sa.Column("markdown_path", sa.String(length=1024), nullable=True),
        sa.Column("pdf_path", sa.String(length=1024), nullable=True),
    )
    op.create_index("ix_reports_period", "reports", ["period"])
    op.create_index("ix_reports_generated_at", "reports", ["generated_at"])

    op.create_table(
        "app_config",
        sa.Column("key", sa.String(length=128), primary_key=True),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("app_config")
    op.drop_index("ix_reports_generated_at", table_name="reports")
    op.drop_index("ix_reports_period", table_name="reports")
    op.drop_table("reports")
    op.drop_index("ix_updates_dedup_hash", table_name="updates")
    op.drop_index("ix_updates_vendor", table_name="updates")
    op.drop_index("ix_updates_discovered_at", table_name="updates")
    op.drop_index("ix_updates_desk_id", table_name="updates")
    op.drop_table("updates")
    op.drop_table("research_runs")
