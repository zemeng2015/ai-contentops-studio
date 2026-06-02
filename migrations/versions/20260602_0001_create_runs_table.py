"""Create runs table.

Revision ID: 20260602_0001
Revises: None
Create Date: 2026-06-02
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260602_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "runs",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("topic", sa.Text(), nullable=False),
        sa.Column("slug", sa.String(length=120), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("artifact_dir", sa.Text(), nullable=False),
        sa.Column("published_url", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_runs_slug", "runs", ["slug"], unique=False)
    op.create_index("ix_runs_status", "runs", ["status"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_runs_status", table_name="runs")
    op.drop_index("ix_runs_slug", table_name="runs")
    op.drop_table("runs")
