"""Skinslink offer ids up to 300 characters (hex ids of offers held in stock).

Revision ID: 0020_skinslink_offer_ids
Revises: 0019_orders_fx_uplift
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0020_skinslink_offer_ids"
down_revision: str | None = "0019_orders_fx_uplift"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Widen the id columns (a widening ALTER rewrites nothing in Postgres)."""
    op.alter_column("skinslink_items", "id", type_=sa.String(300), existing_nullable=False)
    op.alter_column(
        "skinslink_purchases", "asset_id", type_=sa.String(300), existing_nullable=False
    )
    op.alter_column("orders", "offer_id", type_=sa.String(310), existing_nullable=True)


def downgrade() -> None:
    """Narrow them back; long hex ids must be gone first."""
    op.execute("DELETE FROM skinslink_items WHERE length(id) > 32")
    op.alter_column("orders", "offer_id", type_=sa.String(48), existing_nullable=True)
    op.alter_column("skinslink_purchases", "asset_id", type_=sa.String(32), existing_nullable=False)
    op.alter_column("skinslink_items", "id", type_=sa.String(32), existing_nullable=False)
