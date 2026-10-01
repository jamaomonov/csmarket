"""payments: ix_payments_order on order_id (order attempts are looked up by their order)

``hooks.ensure_attempt`` finds an order's live attempt by ``order_id``, the kassa sweeps and
the admin payment detail follow it too; without an index each is a scan of ``payments``.

Revision ID: 0014_payments_order_id_idx
Revises: 0013_orders_skin_trades
Create Date: 2026-10-02
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0014_payments_order_id_idx"
down_revision: str | None = "0013_orders_skin_trades"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Index ``payments.order_id``."""
    op.create_index("ix_payments_order", "payments", ["order_id"])


def downgrade() -> None:
    """Drop the index."""
    op.drop_index("ix_payments_order", table_name="payments")
