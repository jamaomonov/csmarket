"""Stickers and charms decoded from inspect links (2026-10-07).

``skin_items.def_index`` names a sticker or a charm the way an inspect link does;
``skinslink_items.stickers`` / ``keychains`` hold what each listing's link carries.

Revision ID: 0021_inspect_stickers
Revises: 0020_skinslink_offer_ids
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0021_inspect_stickers"
down_revision: str | None = "0020_skinslink_offer_ids"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the columns and the lookup index (empty until the next import / mirror write)."""
    op.add_column("skin_items", sa.Column("def_index", sa.Integer(), nullable=True))
    op.create_index("ix_skin_items_category_def_index", "skin_items", ["category", "def_index"])
    for column in ("stickers", "keychains"):
        op.add_column(
            "skinslink_items",
            sa.Column(
                column,
                postgresql.JSONB(),
                nullable=False,
                server_default=sa.text("'[]'::jsonb"),
            ),
        )


def downgrade() -> None:
    """Drop them."""
    op.drop_column("skinslink_items", "keychains")
    op.drop_column("skinslink_items", "stickers")
    op.drop_index("ix_skin_items_category_def_index", table_name="skin_items")
    op.drop_column("skin_items", "def_index")
