"""public API orders: trade_sent_at, client_order_id unique per owner

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
    """Stamp when the offer went out; make ``client_order_id`` unique per owner, not per key.

    A reissued key must still see its owner's orders and must not buy twice under an old
    ``client_order_id``. ``GET /public/orders`` reads by owner on ``ix_orders_user_created``.
    """
    op.add_column("orders", sa.Column("trade_sent_at", sa.DateTime(timezone=True), nullable=True))
    op.drop_constraint("uq_orders_api_key_id_client_order_id", "orders", type_="unique")
    op.create_index(
        "uq_orders_user_client_order_id",
        "orders",
        ["user_id", "client_order_id"],
        unique=True,
        postgresql_where=sa.text("channel = 'api'"),
    )


def downgrade() -> None:
    """Back to one ``client_order_id`` per key; drop the stamp."""
    op.drop_index("uq_orders_user_client_order_id", table_name="orders")
    op.create_unique_constraint(
        "uq_orders_api_key_id_client_order_id", "orders", ["api_key_id", "client_order_id"]
    )
    op.drop_column("orders", "trade_sent_at")
