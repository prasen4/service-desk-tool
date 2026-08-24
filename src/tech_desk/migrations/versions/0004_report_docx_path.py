"""Add docx_path column to reports table (branded Technology Desk Report .docx).

Revision ID: 0004_report_docx_path
Revises: 0003_position_papers
Create Date: 2026-08-23

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0004_report_docx_path"
down_revision: Union[str, None] = "0003_position_papers"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("reports") as batch_op:
        batch_op.add_column(sa.Column("docx_path", sa.String(length=1024), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("reports") as batch_op:
        batch_op.drop_column("docx_path")
