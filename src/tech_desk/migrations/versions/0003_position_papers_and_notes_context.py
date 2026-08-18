"""Position papers table + report/update context columns (custom instructions,
who-is-affected-first update framing).

Revision ID: 0003_position_papers_and_notes_context
Revises: 0002_vendor_profiles_and_jobs
Create Date: 2026-08-10

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0003_position_papers_and_notes_context"
down_revision: Union[str, None] = "0002_vendor_profiles_and_jobs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("updates") as batch_op:
        batch_op.add_column(
            sa.Column("who_is_affected_first", sa.String(length=256), nullable=False, server_default="")
        )

    with op.batch_alter_table("research_runs") as batch_op:
        batch_op.add_column(sa.Column("custom_instructions", sa.Text(), nullable=True))

    with op.batch_alter_table("reports") as batch_op:
        batch_op.add_column(sa.Column("custom_instructions", sa.Text(), nullable=True))

    op.create_table(
        "position_papers",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("vendor", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="running"),
        sa.Column("custom_prompt", sa.Text(), nullable=False, server_default=""),
        sa.Column("research_brief_json", sa.Text(), nullable=True),
        sa.Column("docx_path", sa.String(length=1024), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("generated_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_position_papers_vendor", "position_papers", ["vendor"])
    op.create_index("ix_position_papers_created_at", "position_papers", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_position_papers_created_at", table_name="position_papers")
    op.drop_index("ix_position_papers_vendor", table_name="position_papers")
    op.drop_table("position_papers")

    with op.batch_alter_table("reports") as batch_op:
        batch_op.drop_column("custom_instructions")

    with op.batch_alter_table("research_runs") as batch_op:
        batch_op.drop_column("custom_instructions")

    with op.batch_alter_table("updates") as batch_op:
        batch_op.drop_column("who_is_affected_first")
