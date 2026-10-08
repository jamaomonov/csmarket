"""public API orders: trade_sent_at, the key's newest-first index

Revision ID: 0028_public_api_orders
Revises: 0027_public_api
Create Date: 2026-10-09
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0028_public_api_orders"
down_revision: str | None = "0027_public_api"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Stamp when the offer went out; index ``GET /public/orders``."""
    op.add_column("orders", sa.Column("trade_sent_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index(
        "ix_orders_api_key_created",
        "orders",
        ["api_key_id", sa.text("created_at DESC")],
        postgresql_where=sa.text("api_key_id IS NOT NULL"),
    )


def downgrade() -> None:
    """Drop the index and the stamp."""
    op.drop_index("ix_orders_api_key_created", table_name="orders")
    op.drop_column("orders", "trade_sent_at")
