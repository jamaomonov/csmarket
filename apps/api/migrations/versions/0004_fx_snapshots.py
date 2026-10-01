"""fx_snapshots: every CBU USD/UZS rate we priced with

Revision ID: 0004_fx_snapshots
Revises: 0003_skins_catalog
Create Date: 2026-10-01
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_fx_snapshots"
down_revision: str | None = "0003_skins_catalog"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "fx_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("usd_uzs", sa.Numeric(12, 4), nullable=False),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column(
            "fetched_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("usd_uzs > 0", name="usd_uzs_positive"),
    )
    op.create_index("ix_fx_snapshots_fetched_at", "fx_snapshots", ["fetched_at"])


def downgrade() -> None:
    op.drop_index("ix_fx_snapshots_fetched_at", table_name="fx_snapshots")
    op.drop_table("fx_snapshots")
