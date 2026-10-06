"""orders.fx_uplift_pct — the uplift on the CBU rate an order was priced with (ADR-0011).

Revision ID: 0019_orders_fx_uplift
Revises: 0018_skinslink
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019_orders_fx_uplift"
down_revision: str | None = "0018_skinslink"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the column; every earlier order was priced at the CBU rate (0)."""
    op.add_column(
        "orders",
        sa.Column("fx_uplift_pct", sa.Numeric(5, 2), nullable=False, server_default=sa.text("0")),
    )


def downgrade() -> None:
    """Drop the column."""
    op.drop_column("orders", "fx_uplift_pct")
