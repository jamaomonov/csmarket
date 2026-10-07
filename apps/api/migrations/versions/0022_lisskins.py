"""lisskins: offers, state and purchases; skin_items and orders learn a third source

LIS-SKINS becomes a buy source beside Skinslink (spec 2026-10-07, ADR-0012): the 10
cheapest instant lots per catalogue item from its public export, the snapshot's freshness,
and the purchase behind each LIS-SKINS order.

Revision ID: 0022_lisskins
Revises: 0021_inspect_stickers
Create Date: 2026-10-07
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0022_lisskins"
down_revision: str | None = "0021_inspect_stickers"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ATTENTION = (
    "'buy_unconfirmed', 'ambiguous_trade', 'rolled_back', 'source_forbidden', 'audit_divergence'"
)


def _ts(name: str) -> sa.Column[object]:
    return sa.Column(
        name,
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("CURRENT_TIMESTAMP"),
    )


def _at(name: str) -> sa.Column[object]:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=True)


def _tables() -> None:
    op.create_table(
        "lisskins_offers",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=False),
        sa.Column(
            "skin_item_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("skin_items.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("price_units", sa.BigInteger(), nullable=False),
        sa.Column("float_value", sa.Numeric(7, 6), nullable=True),
        sa.Column("paint_seed", sa.Integer(), nullable=True),
        sa.Column("asset_id", sa.String(32), nullable=True),
        sa.Column("inspect_url", sa.Text(), nullable=True),
        sa.Column(
            "stickers", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")
        ),
        _ts("updated_at"),
    )
    op.create_index(
        "ix_lisskins_offers_item_price", "lisskins_offers", ["skin_item_id", "price_units"]
    )
    op.create_table(
        "lisskins_state",
        sa.Column("id", sa.Integer(), primary_key=True),
        _at("snapshot_at"),
        _at("synced_at"),
        sa.Column("lots", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.CheckConstraint("id = 1", name="singleton"),
    )
    op.create_table(
        "lisskins_purchases",
        sa.Column(
            "order_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("orders.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("custom_id", sa.String(64), nullable=False),
        sa.Column("skin_id", sa.BigInteger(), nullable=False),
        sa.Column("paid_units", sa.Integer(), nullable=False),
        sa.Column("purchase_id", sa.BigInteger(), nullable=True),
        sa.Column("status", sa.String(16), nullable=True),
        sa.Column("return_reason", sa.String(32), nullable=True),
        sa.Column("error", sa.String(32), nullable=True),
        sa.Column("steam_trade_offer_id", sa.String(32), nullable=True),
        _at("offer_expiry_at"),
        sa.Column("amount_units", sa.Integer(), nullable=True),
        sa.Column("buy_pending", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        _at("buy_unconfirmed_at"),
        sa.Column("attention_reason", sa.String(32), nullable=True),
        _at("last_polled_at"),
        _at("resolved_at"),
        sa.Column("resolved_by", sa.String(64), nullable=True),
        sa.Column("resolved_note", sa.Text(), nullable=True),
        _ts("created_at"),
        _ts("updated_at"),
        sa.UniqueConstraint("custom_id", name="uq_lisskins_purchases_custom_id"),
        sa.CheckConstraint(f"attention_reason IN ({_ATTENTION})", name="attention_reason"),
    )


def upgrade() -> None:
    """Create the LIS-SKINS tables; add the roll-up columns; allow the third source."""
    _tables()
    op.add_column("skin_items", sa.Column("lisskins_min_units", sa.BigInteger(), nullable=True))
    op.add_column(
        "skin_items",
        sa.Column("lisskins_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    op.drop_constraint("source", "orders", type_="check")
    op.create_check_constraint("source", "orders", "source IN ('waxpeer', 'skinslink', 'lisskins')")


def downgrade() -> None:
    """Back to two sources (LIS-SKINS orders must be gone: the check refuses them)."""
    op.drop_constraint("source", "orders", type_="check")
    op.create_check_constraint("source", "orders", "source IN ('waxpeer', 'skinslink')")
    op.drop_column("skin_items", "lisskins_count")
    op.drop_column("skin_items", "lisskins_min_units")
    op.drop_table("lisskins_purchases")
    op.drop_table("lisskins_state")
    op.drop_index("ix_lisskins_offers_item_price", table_name="lisskins_offers")
    op.drop_table("lisskins_offers")
