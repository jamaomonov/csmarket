"""orders: trade_link_erased_at — when the nightly erase masked the order's trade link

Thirty days after an order ends, its trade-link token is replaced by the masked form
(decision D3, M4b ruling R11); the stamp makes the erase idempotent.

Revision ID: 0017_orders_trade_link_erased
Revises: 0016_orders_dashboard
Create Date: 2026-10-02
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017_orders_trade_link_erased"
down_revision: str | None = "0016_orders_dashboard"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the nullable stamp."""
    op.add_column(
        "orders", sa.Column("trade_link_erased_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    """Drop the stamp (erased links stay masked: a token is not recoverable)."""
    op.drop_column("orders", "trade_link_erased_at")
