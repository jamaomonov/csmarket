"""«Мои сделки» v2: the deal's guarantor, and the catalogue's picture for every desk item
that has none (spec 2026-10-31-desk-v2, ADR-0027 amendment 2026-10-31).

The picture is ours by ``market_hash_name`` (the phase ignored, an item without a phase
first). The downgrade drops the column and leaves the pictures: they are harmless.

Revision ID: 0046_desk_v2
Revises: 0045_desk_bot
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0046_desk_v2"
down_revision: str | None = "0045_desk_bot"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("desk_deals", sa.Column("guarantor", sa.String(120), nullable=True))
    op.execute(
        """
        UPDATE desk_items AS d
        SET image_url = (
            SELECT s.image_url FROM skin_items AS s
            WHERE s.market_hash_name = d.name AND s.image_url IS NOT NULL AND s.image_url <> ''
            ORDER BY s.phase <> '', s.id
            LIMIT 1
        )
        WHERE d.image_url IS NULL
        """
    )


def downgrade() -> None:
    op.drop_column("desk_deals", "guarantor")
