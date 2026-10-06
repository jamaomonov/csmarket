"""skinslink: the mirror, state, purchases and checks; skin_items and orders learn a second source

Skinslink becomes a second buy source beside Waxpeer (spec 2026-10-06, ADR-0010). The failure
and attention codes that named Waxpeer become source-neutral (``source_low_balance``,
``source_forbidden``); existing rows are mapped.

Revision ID: 0018_skinslink
Revises: 0017_orders_trade_link_erased
Create Date: 2026-10-06
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0018_skinslink"
down_revision: str | None = "0017_orders_trade_link_erased"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ATTENTION_OLD = (
    "'buy_unconfirmed', 'ambiguous_trade', 'rolled_back', 'waxpeer_forbidden', 'audit_divergence'"
)
_ATTENTION_NEW = (
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
        "skinslink_items",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("market_hash_name", sa.String(255), nullable=False),
        sa.Column("phase", sa.String(16), nullable=False, server_default=sa.text("''")),
        sa.Column("price_units", sa.BigInteger(), nullable=False),
        sa.Column("float_value", sa.Numeric(7, 6), nullable=True),
        sa.Column("paint_seed", sa.Integer(), nullable=True),
        sa.Column("inspect_url", sa.Text(), nullable=True),
        sa.Column("image_url", sa.Text(), nullable=True),
        sa.Column(
            "skin_item_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("skin_items.id", ondelete="SET NULL"),
            nullable=True,
        ),
        _ts("updated_at"),
    )
    op.create_index(
        "ix_skinslink_items_item_price", "skinslink_items", ["skin_item_id", "price_units"]
    )
    op.create_table(
        "skinslink_state",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("cursor", sa.String(64), nullable=True),
        _at("mirror_synced_at"),
        _at("full_loaded_at"),
        sa.CheckConstraint("id = 1", name="singleton"),
    )
    op.create_table(
        "skinslink_purchases",
        sa.Column(
            "order_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("orders.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("merchant_tx_id", sa.String(64), nullable=False),
        sa.Column("asset_id", sa.String(32), nullable=False),
        sa.Column("paid_units", sa.Integer(), nullable=False),
        sa.Column("purchase_id", sa.BigInteger(), nullable=True),
        sa.Column("status", sa.String(16), nullable=True),
        sa.Column("offer_id", sa.String(32), nullable=True),
        sa.Column("fail_reason", sa.String(48), nullable=True),
        sa.Column("amount_units", sa.Integer(), nullable=True),
        _at("hold_end_date"),
        sa.Column("buy_pending", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        _at("buy_unconfirmed_at"),
        sa.Column("attention_reason", sa.String(32), nullable=True),
        _at("last_polled_at"),
        _at("resolved_at"),
        sa.Column("resolved_by", sa.String(64), nullable=True),
        sa.Column("resolved_note", sa.Text(), nullable=True),
        _ts("created_at"),
        _ts("updated_at"),
        sa.UniqueConstraint("purchase_id", name="uq_skinslink_purchases_purchase_id"),
        sa.UniqueConstraint("merchant_tx_id", name="uq_skinslink_purchases_merchant_tx_id"),
        sa.CheckConstraint(
            f"attention_reason IN ({_ATTENTION_NEW})",
            name="attention_reason",
        ),
    )
    op.create_table(
        "skinslink_checks",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("purchase_id", sa.BigInteger(), nullable=False),
        _ts("created_at"),
        _at("claimed_at"),
    )
    op.create_index("ix_skinslink_checks_queue", "skinslink_checks", ["claimed_at", "created_at"])


def upgrade() -> None:
    """Create the Skinslink tables; add the source columns; rename the Waxpeer-named codes."""
    _tables()
    op.add_column("skin_items", sa.Column("skinslink_min_units", sa.BigInteger(), nullable=True))
    op.add_column(
        "skin_items",
        sa.Column("skinslink_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    op.add_column(
        "orders",
        sa.Column("source", sa.String(12), nullable=False, server_default=sa.text("'waxpeer'")),
    )
    op.add_column("orders", sa.Column("offer_id", sa.String(48), nullable=True))
    op.alter_column("orders", "listing_id", existing_type=sa.BigInteger(), nullable=True)
    op.create_check_constraint("source", "orders", "source IN ('waxpeer', 'skinslink')")
    op.execute(
        "UPDATE orders SET offer_id = 'wx:' || listing_id"
        " WHERE offer_id IS NULL AND listing_id IS NOT NULL"
    )
    op.execute(
        "UPDATE orders SET failure_reason = 'source_low_balance'"
        " WHERE failure_reason = 'waxpeer_low_balance'"
    )
    op.drop_constraint("attention_reason", "skin_trades", type_="check")
    op.execute(
        "UPDATE skin_trades SET attention_reason = 'source_forbidden'"
        " WHERE attention_reason = 'waxpeer_forbidden'"
    )
    op.create_check_constraint(
        "attention_reason", "skin_trades", f"attention_reason IN ({_ATTENTION_NEW})"
    )


def downgrade() -> None:
    """Map the codes back, drop the columns (Skinslink orders must be gone) and the tables."""
    op.drop_constraint("attention_reason", "skin_trades", type_="check")
    op.execute(
        "UPDATE skin_trades SET attention_reason = 'waxpeer_forbidden'"
        " WHERE attention_reason = 'source_forbidden'"
    )
    op.create_check_constraint(
        "attention_reason", "skin_trades", f"attention_reason IN ({_ATTENTION_OLD})"
    )
    op.execute(
        "UPDATE orders SET failure_reason = 'waxpeer_low_balance'"
        " WHERE failure_reason = 'source_low_balance'"
    )
    op.drop_constraint("source", "orders", type_="check")
    op.alter_column("orders", "listing_id", existing_type=sa.BigInteger(), nullable=False)
    op.drop_column("orders", "offer_id")
    op.drop_column("orders", "source")
    op.drop_column("skin_items", "skinslink_count")
    op.drop_column("skin_items", "skinslink_min_units")
    op.drop_table("skinslink_checks")
    op.drop_table("skinslink_purchases")
    op.drop_table("skinslink_state")
    op.drop_index("ix_skinslink_items_item_price", table_name="skinslink_items")
    op.drop_table("skinslink_items")
