"""skins: each skin's own colours, read from its picture

Spec 2026-10-14-skin-colors: ``skin_items.colors`` (one or two of twelve keys, GIN-indexed for
the catalogue's ``color`` filter), ``colors_image`` (the picture they were read from) and
``colors_manual`` (an admin's choice the job never overwrites). Every row starts with ``{}``;
the ``skins.colors`` job fills them.

Revision ID: 0035_skin_colors
Revises: 0034_payout_bank_fee
Create Date: 2026-10-14
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0035_skin_colors"
down_revision: str | None = "0034_payout_bank_fee"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the colour columns and their index."""
    op.add_column(
        "skin_items",
        sa.Column(
            "colors",
            postgresql.ARRAY(sa.String(16)),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
    )
    op.add_column("skin_items", sa.Column("colors_image", sa.Text(), nullable=True))
    op.add_column(
        "skin_items",
        sa.Column("colors_manual", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.create_index("ix_skin_items_colors", "skin_items", ["colors"], postgresql_using="gin")


def downgrade() -> None:
    """Drop them."""
    op.drop_index("ix_skin_items_colors", table_name="skin_items")
    op.drop_column("skin_items", "colors_manual")
    op.drop_column("skin_items", "colors_image")
    op.drop_column("skin_items", "colors")
