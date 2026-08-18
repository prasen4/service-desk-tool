"""Vendor CRM (profiles, notes, attachments, status pipeline) + durable job history.

Revision ID: 0002_vendor_profiles_and_jobs
Revises: 0001_baseline
Create Date: 2026-07-29

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0002_vendor_profiles_and_jobs"
down_revision: Union[str, None] = "0001_baseline"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "vendors",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="identified"),
        sa.Column("owner", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_vendors_name", "vendors", ["name"], unique=True)

    op.create_table(
        "vendor_notes",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("vendor_id", sa.Integer(), sa.ForeignKey("vendors.id", ondelete="CASCADE"), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("author", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_vendor_notes_vendor_id", "vendor_notes", ["vendor_id"])
    op.create_index("ix_vendor_notes_created_at", "vendor_notes", ["created_at"])

    op.create_table(
        "vendor_attachments",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("vendor_id", sa.Integer(), sa.ForeignKey("vendors.id", ondelete="CASCADE"), nullable=False),
        sa.Column("note_id", sa.Integer(), sa.ForeignKey("vendor_notes.id", ondelete="SET NULL"), nullable=True),
        sa.Column("original_filename", sa.String(length=256), nullable=False),
        sa.Column("stored_filename", sa.String(length=256), nullable=False),
        sa.Column("content_type", sa.String(length=128), nullable=False, server_default="application/octet-stream"),
        sa.Column("size_bytes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("uploaded_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_vendor_attachments_vendor_id", "vendor_attachments", ["vendor_id"])
    op.create_index("ix_vendor_attachments_note_id", "vendor_attachments", ["note_id"])
    op.create_index("ix_vendor_attachments_uploaded_at", "vendor_attachments", ["uploaded_at"])

    op.create_table(
        "vendor_status_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("vendor_id", sa.Integer(), sa.ForeignKey("vendors.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
        sa.Column("changed_by", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_vendor_status_events_vendor_id", "vendor_status_events", ["vendor_id"])
    op.create_index("ix_vendor_status_events_created_at", "vendor_status_events", ["created_at"])

    op.create_table(
        "jobs",
        sa.Column("id", sa.String(length=32), primary_key=True),
        sa.Column("job_type", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("message", sa.String(length=512), nullable=False, server_default="Queued"),
        sa.Column("progress", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("result_json", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
    )
    op.create_index("ix_jobs_status", "jobs", ["status"])
    op.create_index("ix_jobs_created_at", "jobs", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_jobs_created_at", table_name="jobs")
    op.drop_index("ix_jobs_status", table_name="jobs")
    op.drop_table("jobs")

    op.drop_index("ix_vendor_status_events_created_at", table_name="vendor_status_events")
    op.drop_index("ix_vendor_status_events_vendor_id", table_name="vendor_status_events")
    op.drop_table("vendor_status_events")

    op.drop_index("ix_vendor_attachments_uploaded_at", table_name="vendor_attachments")
    op.drop_index("ix_vendor_attachments_note_id", table_name="vendor_attachments")
    op.drop_index("ix_vendor_attachments_vendor_id", table_name="vendor_attachments")
    op.drop_table("vendor_attachments")

    op.drop_index("ix_vendor_notes_created_at", table_name="vendor_notes")
    op.drop_index("ix_vendor_notes_vendor_id", table_name="vendor_notes")
    op.drop_table("vendor_notes")

    op.drop_index("ix_vendors_name", table_name="vendors")
    op.drop_table("vendors")


