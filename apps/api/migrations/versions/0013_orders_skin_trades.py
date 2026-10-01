"""orders: orders and skin_trades; payments.order_id foreign key and purpose check

``orders`` is the customer's purchase and the worker's queue; ``skin_trades`` is the
Waxpeer purchase and the Steam trade behind one order (spec §5, rulings R1–R3). ``payments``
gains the ``order_id → orders.id`` key and ``ck_payments_purpose_order``. Downgrade in reverse.

Revision ID: 0013_orders_skin_trades
Revises: 0012_payments_number_pattern_ops
Create Date: 2026-10-02
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0013_orders_skin_trades"
down_revision: str | None = "0012_payments_number_pattern_ops"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PAYMENT_ORDER_FK = "fk_payments_order_id_orders"
_PAYMENT_ORDER_CK = "ck_payments_purpose_order"


def _ts(name: str) -> sa.Column[object]:
    return sa.Column(
        name,
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("CURRENT_TIMESTAMP"),
    )


def _at(name: str) -> sa.Column[object]:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=True)


def _fk(name: str, target: str, ondelete: str) -> sa.Column[object]:
    return sa.Column(
        name,
        postgresql.UUID(as_uuid=False),
        sa.ForeignKey(target, ondelete=ondelete),
        nullable=False,
    )


def _create_orders() -> None:
    op.create_table(
        "orders",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("number", sa.String(8), nullable=False),
        _fk("user_id", "users.id", "RESTRICT"),
        sa.Column("status", sa.String(12), nullable=False, server_default=sa.text("'pending'")),
        _fk("skin_item_id", "skin_items.id", "RESTRICT"),
        sa.Column("market_hash_name", sa.String(255), nullable=False),
        sa.Column("phase", sa.String(16), nullable=False, server_default=sa.text("''")),
        sa.Column("slug", sa.String(255), nullable=False),
        sa.Column("listing_id", sa.BigInteger(), nullable=False),
        sa.Column("cost_units", sa.Integer(), nullable=False),
        sa.Column("cost_usd", sa.Numeric(12, 6), nullable=False),
        sa.Column("price_usd", sa.Numeric(12, 6), nullable=False),
        sa.Column("price_uzs", sa.Numeric(14, 0), nullable=False),
        _fk("fx_snapshot_id", "fx_snapshots.id", "RESTRICT"),
        sa.Column("trade_link", sa.Text(), nullable=False),
        sa.Column("idempotency_key", sa.String(160), nullable=False),
        sa.Column("paid_with", sa.String(16), nullable=True),
        _ts("created_at"),
        _ts("updated_at"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        _at("paid_at"),
        _at("delivered_at"),
        _at("cancelled_at"),
        _at("failed_at"),
        _at("refunded_at"),
        sa.Column("refunded_to", sa.String(8), nullable=True),
        sa.Column("failure_reason", sa.String(32), nullable=True),
        _at("claimed_at"),
        sa.Column("claimed_by", sa.String(64), nullable=True),
        _at("next_check_at"),
        sa.UniqueConstraint("number", name="uq_orders_number"),
        sa.UniqueConstraint("user_id", "idempotency_key", name="uq_orders_user_id_idempotency_key"),
        # Bare suffixes: the metadata naming convention adds the ``ck_orders_`` prefix.
        sa.CheckConstraint(
            "status IN ('pending', 'paid', 'buying', 'trade_sent', 'delivered', 'cancelled', "
            "'failed', 'returned')",
            name="status",
        ),
        sa.CheckConstraint("refunded_to IN ('balance')", name="refunded_to"),
    )
    op.create_index("ix_orders_status_next_check", "orders", ["status", "next_check_at"])
    op.create_index("ix_orders_user_created", "orders", ["user_id", sa.text("created_at DESC")])
    op.create_index(
        "ix_orders_number", "orders", ["number"], postgresql_ops={"number": "text_pattern_ops"}
    )


def _create_skin_trades() -> None:
    op.create_table(
        "skin_trades",
        sa.Column(
            "order_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("orders.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("project_id", sa.String(64), nullable=False),
        sa.Column("waxpeer_id", sa.BigInteger(), nullable=True),
        sa.Column("listing_id", sa.BigInteger(), nullable=False),
        sa.Column("paid_units", sa.Integer(), nullable=False),
        sa.Column("bought_units", sa.Integer(), nullable=True),
        sa.Column("status", sa.SmallInteger(), nullable=True),
        sa.Column("escrow_status", sa.String(32), nullable=True),
        sa.Column("trade_id", sa.String(32), nullable=True),
        _at("send_until"),
        _at("release_date"),
        sa.Column("is_released", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        _at("accepted_at"),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("penalties", postgresql.JSONB(), nullable=True),
        sa.Column(
            "seller", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column("buy_pending", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        _at("buy_unconfirmed_at"),
        sa.Column("attention_reason", sa.String(32), nullable=True),
        sa.Column("audit_verdict", sa.String(32), nullable=True),
        _at("last_polled_at"),
        _at("resolved_at"),
        sa.Column("resolved_by", sa.String(64), nullable=True),
        sa.Column("resolved_note", sa.Text(), nullable=True),
        _ts("created_at"),
        _ts("updated_at"),
        sa.UniqueConstraint("project_id", name="uq_skin_trades_project_id"),
        sa.CheckConstraint(
            "attention_reason IN ('buy_unconfirmed', 'ambiguous_trade', 'rolled_back', "
            "'waxpeer_forbidden', 'audit_divergence')",
            name="attention_reason",
        ),
    )
    op.create_index("ix_skin_trades_protection", "skin_trades", ["status", "is_released"])
    op.create_index(
        "ix_skin_trades_attention",
        "skin_trades",
        ["attention_reason"],
        postgresql_where=sa.text("attention_reason IS NOT NULL AND resolved_at IS NULL"),
    )
    op.create_index("ix_skin_trades_created_at", "skin_trades", ["created_at"])


def upgrade() -> None:
    """Create ``orders`` and ``skin_trades``, then tie ``payments.order_id`` to orders."""
    _create_orders()
    _create_skin_trades()
    op.create_foreign_key(
        op.f(_PAYMENT_ORDER_FK), "payments", "orders", ["order_id"], ["id"], ondelete="RESTRICT"
    )
    op.create_check_constraint(
        op.f(_PAYMENT_ORDER_CK), "payments", "(purpose = 'order') = (order_id IS NOT NULL)"
    )


def downgrade() -> None:
    """Untie ``payments`` and drop both tables."""
    op.drop_constraint(op.f(_PAYMENT_ORDER_CK), "payments", type_="check")
    op.drop_constraint(op.f(_PAYMENT_ORDER_FK), "payments", type_="foreignkey")
    for index in (
        "ix_skin_trades_created_at",
        "ix_skin_trades_attention",
        "ix_skin_trades_protection",
    ):
        op.drop_index(index, table_name="skin_trades")
    op.drop_table("skin_trades")
    for index in ("ix_orders_number", "ix_orders_user_created", "ix_orders_status_next_check"):
        op.drop_index(index, table_name="orders")
    op.drop_table("orders")
