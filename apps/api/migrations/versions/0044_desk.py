"""The owner's personal trading desk, «Мои сделки» (ADR-0027): deals, items, Skinslink
deposits, the profit ledger and withdrawals.

Revision ID: 0044_desk
Revises: 0043_referrals
"""

from collections.abc import Sequence
from typing import Any  # Column[Any]: a column spec of any type

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0044_desk"
down_revision: str | None = "0043_referrals"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UUID = postgresql.UUID(as_uuid=False)
_USD = sa.Numeric(18, 6)


def _ts(name: str) -> sa.Column[Any]:
    return sa.Column(
        name,
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("CURRENT_TIMESTAMP"),
    )


def _at(name: str) -> sa.Column[Any]:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=True)


def _fk(name: str, table: str, *, nullable: bool = False) -> sa.Column[Any]:
    return sa.Column(
        name, _UUID, sa.ForeignKey(f"{table}.id", ondelete="RESTRICT"), nullable=nullable
    )


def _deals() -> None:
    op.create_table(
        "desk_deals",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("trader", sa.String(120), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("trade_link", sa.Text(), nullable=True),
        sa.Column("paid_amount", _USD, nullable=True),
        sa.Column("paid_currency", sa.String(3), nullable=True),
        sa.Column("rate", sa.Numeric(12, 4), nullable=True),
        sa.Column("paid_usd", _USD, nullable=True),
        sa.Column("method", sa.String(16), nullable=False, server_default=sa.text("'direct'")),
        _at("paid_at"),
        _at("guarantor_released_at"),
        _ts("created_at"),
        _ts("updated_at"),
        sa.CheckConstraint(
            "status IN ('agreed', 'paid', 'received', 'closed', 'cancelled', 'reverted')",
            name="status",
        ),
        sa.CheckConstraint("method IN ('direct', 'guarantor')", name="method"),
        sa.CheckConstraint(
            "paid_currency IS NULL OR paid_currency IN ('UZS', 'USD')", name="currency"
        ),
        sa.CheckConstraint(
            "paid_amount IS NULL OR (paid_amount > 0 AND paid_currency IS NOT NULL"
            " AND paid_usd IS NOT NULL AND (paid_currency = 'USD' OR rate > 0))",
            name="price",
        ),
    )
    op.create_index("ix_desk_deals_created", "desk_deals", ["created_at"])


def _deposits() -> None:
    op.create_table(
        "desk_deposits",
        sa.Column("id", _UUID, primary_key=True),
        _fk("deal_id", "desk_deals"),
        sa.Column("skinslink_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("amount_usd", _USD, nullable=True),
        sa.Column("trade_offer_id", sa.String(40), nullable=True),
        sa.Column("offer_expiry_at", sa.String(40), nullable=True),
        sa.Column("hold_end_date", sa.String(40), nullable=True),
        sa.Column("fail_reason", sa.String(64), nullable=True),
        _ts("next_check_at"),
        _at("accepted_at"),
        _at("credited_at"),
        _at("reverted_at"),
        _ts("created_at"),
    )
    op.create_index("ix_desk_deposits_deal", "desk_deposits", ["deal_id"])
    op.create_index(
        "ix_desk_deposits_due",
        "desk_deposits",
        ["next_check_at"],
        postgresql_where=sa.text("status NOT IN ('failed', 'canceled', 'reverted')"),
    )


def _items() -> None:
    op.create_table(
        "desk_items",
        sa.Column("id", _UUID, primary_key=True),
        _fk("deal_id", "desk_deals"),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("asset_id", sa.String(32), nullable=True),
        sa.Column("image_url", sa.Text(), nullable=True),
        sa.Column("skinslink_usd", _USD, nullable=True),
        sa.Column("destination", sa.String(16), nullable=False),
        sa.Column("cost_usd", _USD, nullable=True),
        sa.Column("state", sa.String(16), nullable=False, server_default="open"),
        _fk("deposit_id", "desk_deposits", nullable=True),
        sa.Column("sold_where", sa.String(120), nullable=True),
        sa.Column("sold_amount", _USD, nullable=True),
        sa.Column("sold_currency", sa.String(3), nullable=True),
        sa.Column("sold_rate", sa.Numeric(12, 4), nullable=True),
        sa.Column("sold_usd", _USD, nullable=True),
        _at("resolved_at"),
        sa.Column("note", sa.Text(), nullable=True),
        sa.CheckConstraint("destination IN ('skinslink', 'stock')", name="destination"),
        sa.CheckConstraint(
            "state IN ('open', 'sent', 'credited', 'sold', 'written_off', 'reverted')",
            name="state",
        ),
    )
    op.create_index("ix_desk_items_deal", "desk_items", ["deal_id"])
    op.create_index(
        "ix_desk_items_stock",
        "desk_items",
        ["deal_id"],
        postgresql_where=sa.text("destination = 'stock' AND state = 'open'"),
    )


def _ledger() -> None:
    op.create_table(
        "desk_entries",
        sa.Column("id", _UUID, primary_key=True),
        _fk("deal_id", "desk_deals"),
        _fk("item_id", "desk_items"),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("profit_usd", _USD, nullable=False),
        sa.Column("revenue_usd", _USD, nullable=False, server_default=sa.text("0")),
        _ts("at"),
        sa.CheckConstraint("kind IN ('credit', 'sale', 'revert', 'write_off')", name="kind"),
    )
    op.create_index("uq_desk_entries_item_kind", "desk_entries", ["item_id", "kind"], unique=True)
    op.create_index("ix_desk_entries_at", "desk_entries", ["at"])
    op.create_table(
        "desk_withdrawals",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column("amount_usd", _USD, nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        _ts("at"),
        sa.CheckConstraint("amount_usd > 0", name="amount"),
    )


def upgrade() -> None:
    _deals()
    _deposits()
    _items()
    _ledger()


def downgrade() -> None:
    for table in ("desk_withdrawals", "desk_entries", "desk_items", "desk_deposits", "desk_deals"):
        op.drop_table(table)
