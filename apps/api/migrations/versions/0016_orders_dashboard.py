"""orders: ix_orders_paid_at and ix_orders_refunded_at for the admin dashboard

The dashboard (M4b R9) sums orders paid, and orders refunded, within a window; without these
partial indexes each window is a scan of ``orders``.

Revision ID: 0016_orders_dashboard
Revises: 0015_email_outbox
Create Date: 2026-10-02
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016_orders_dashboard"
down_revision: str | None = "0015_email_outbox"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Index the paid and refunded timestamps where they are set."""
    op.create_index(
        "ix_orders_paid_at",
        "orders",
        ["paid_at"],
        postgresql_where=sa.text("paid_at IS NOT NULL"),
    )
    op.create_index(
        "ix_orders_refunded_at",
        "orders",
        ["refunded_at"],
        postgresql_where=sa.text("refunded_at IS NOT NULL"),
    )


def downgrade() -> None:
    """Drop both indexes."""
    op.drop_index("ix_orders_refunded_at", table_name="orders")
    op.drop_index("ix_orders_paid_at", table_name="orders")
