"""skins: collection, cases and Valve's description from ByMykel

Revision ID: 0031_skin_lore
Revises: 0030_api_key_limits
Create Date: 2026-10-10
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0031_skin_lore"
down_revision: str | None = "0030_api_key_limits"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Three metadata columns the daily import fills; empty until its next run."""
    op.add_column("skin_items", sa.Column("collection", sa.String(128), nullable=True))
    op.add_column(
        "skin_items",
        sa.Column("crates", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
    )
    op.add_column("skin_items", sa.Column("description", sa.Text, nullable=True))


def downgrade() -> None:
    """Drop the three columns."""
    op.drop_column("skin_items", "description")
    op.drop_column("skin_items", "crates")
    op.drop_column("skin_items", "collection")
