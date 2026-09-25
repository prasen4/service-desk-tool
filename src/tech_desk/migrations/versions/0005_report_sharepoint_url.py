"""Add sharepoint_url column to reports table (set when SharePoint upload is
configured and succeeds for a generated report's .docx).

Revision ID: 0005_report_sharepoint_url
Revises: 0004_report_docx_path
Create Date: 2026-09-25

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0005_report_sharepoint_url"
down_revision: Union[str, None] = "0004_report_docx_path"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("reports") as batch_op:
        batch_op.add_column(sa.Column("sharepoint_url", sa.String(length=1024), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("reports") as batch_op:
        batch_op.drop_column("sharepoint_url")
