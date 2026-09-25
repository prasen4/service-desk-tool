"""Add sharepoint_url column to position_papers table (set when SharePoint
upload is configured and succeeds for a generated position paper's .docx).

Revision ID: 0006_position_paper_sharepoint_url
Revises: 0005_report_sharepoint_url
Create Date: 2026-09-25

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0006_position_paper_sharepoint_url"
down_revision: Union[str, None] = "0005_report_sharepoint_url"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("position_papers") as batch_op:
        batch_op.add_column(sa.Column("sharepoint_url", sa.String(length=1024), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("position_papers") as batch_op:
        batch_op.drop_column("sharepoint_url")
