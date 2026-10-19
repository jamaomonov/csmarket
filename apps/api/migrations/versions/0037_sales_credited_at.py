"""sales: an index on credited_at for the analytics' buy-back days

Spec 2026-10-19-analytics: the buy-back P&L of any window reads sales by the day Skinslink
credited them.

Revision ID: 0037_sales_credited_at
Revises: 0036_kassa_fee
Create Date: 2026-10-19
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0037_sales_credited_at"
down_revision: str | None = "0036_kassa_fee"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Index ``sales.credited_at`` (set rows only)."""
    op.create_index(
        "ix_sales_credited_at",
        "sales",
        ["credited_at"],
        postgresql_where=sa.text("credited_at IS NOT NULL"),
    )


def downgrade() -> None:
    """Drop the index."""
    op.drop_index("ix_sales_credited_at", table_name="sales")
