"""orders: the float and pattern of the bought offer

The order page shows the float and paint seed of the very lot the buyer chose; older orders
keep ``NULL`` (the offer is gone, nothing to backfill from).

Revision ID: 0025_order_float_seed
Revises: 0024_sale_credit_blocked
Create Date: 2026-10-08
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0025_order_float_seed"
down_revision: str | None = "0024_sale_credit_blocked"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the two nullable columns."""
    op.add_column("orders", sa.Column("float_value", sa.Numeric(7, 6), nullable=True))
    op.add_column("orders", sa.Column("paint_seed", sa.Integer(), nullable=True))


def downgrade() -> None:
    """Drop them."""
    op.drop_column("orders", "paint_seed")
    op.drop_column("orders", "float_value")
