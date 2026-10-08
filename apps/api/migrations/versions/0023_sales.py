"""sales: users sell skins through Skinslink deposits; cards, payout requests, settings

Spec 2026-10-08, ADR-0016: one row per deposit and its items, saved payout cards (the number
encrypted), card payout requests, the admin's settings document, a check queue; the email
outbox learns three sale letters; the ledger a ``house_skin_buys`` account.

Revision ID: 0023_sales
Revises: 0022_lisskins
Create Date: 2026-10-08
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0023_sales"
down_revision: str | None = "0022_lisskins"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UUID = postgresql.UUID(as_uuid=False)
_SALE_STATUSES = "'creating', 'offered', 'hold', 'credited', 'payout', 'closed', 'reverted'"
_REQUEST_STATUSES = "'waiting_hold', 'to_pay', 'paid', 'rejected', 'canceled'"
_KINDS_OLD = "'receipt', 'trade_sent', 'refunded', 'verify'"
_KINDS_NEW = _KINDS_OLD + ", 'sale_hold', 'sale_paid', 'sale_canceled'"
_ACCOUNTS_OLD = "'user_wallet', 'provider_clearing', 'house_payments_received', 'house_adjustments'"
_ACCOUNTS_NEW = _ACCOUNTS_OLD + ", 'house_skin_buys'"


def _ts(name: str) -> sa.Column[object]:
    return sa.Column(
        name,
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("CURRENT_TIMESTAMP"),
    )


def _at(name: str) -> sa.Column[object]:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=True)


def _fk(name: str, target: str, *, ondelete: str, nullable: bool = False) -> sa.Column[object]:
    return sa.Column(name, _UUID, sa.ForeignKey(target, ondelete=ondelete), nullable=nullable)


def _cards() -> None:
    op.create_table(
        "payout_cards",
        sa.Column("id", _UUID, primary_key=True),
        _fk("user_id", "users.id", ondelete="RESTRICT"),
        sa.Column("type", sa.String(16), nullable=False),
        sa.Column("number_enc", sa.LargeBinary(), nullable=False),
        sa.Column("number_nonce", sa.LargeBinary(), nullable=False),
        sa.Column("last4", sa.String(4), nullable=False),
        _ts("created_at"),
        _at("deleted_at"),
        sa.CheckConstraint("type IN ('uzcard', 'humo', 'uzum_visa')", name="type"),
    )
    op.create_index(
        "ix_payout_cards_user_live",
        "payout_cards",
        ["user_id"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )


def _sales() -> None:
    op.create_table(
        "sales",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column("number", sa.String(8), nullable=False),
        _fk("user_id", "users.id", ondelete="RESTRICT"),
        sa.Column("status", sa.String(16), nullable=False, server_default=sa.text("'creating'")),
        sa.Column("payout_to", sa.String(8), nullable=False),
        _fk("payout_card_id", "payout_cards.id", ondelete="RESTRICT", nullable=True),
        sa.Column("quoted_usd", sa.Numeric(14, 6), nullable=False),
        sa.Column("amount_usd", sa.Numeric(14, 6), nullable=True),
        sa.Column("items_uzs", sa.Numeric(14, 0), nullable=False),
        sa.Column("payout_uzs", sa.Numeric(14, 0), nullable=False),
        sa.Column("rate", sa.Numeric(12, 4), nullable=False),
        sa.Column("margin_usd", sa.Numeric(14, 6), nullable=False),
        sa.Column("trade_id", sa.BigInteger(), nullable=True),
        sa.Column("trade_offer_id", sa.String(32), nullable=True),
        sa.Column("bot_name", sa.String(64), nullable=True),
        _at("offer_expiry_at"),
        _at("hold_end_at"),
        sa.Column("fail_reason", sa.String(48), nullable=True),
        _at("credited_at"),
        sa.Column("attention_reason", sa.String(16), nullable=True),
        sa.Column("idempotency_key", sa.String(160), nullable=False),
        _at("last_polled_at"),
        _ts("created_at"),
        _ts("updated_at"),
        sa.UniqueConstraint("number", name="uq_sales_number"),
        sa.UniqueConstraint("user_id", "idempotency_key", name="uq_sales_user_id_idempotency_key"),
        sa.CheckConstraint(f"status IN ({_SALE_STATUSES})", name="status"),
        sa.CheckConstraint("payout_to IN ('balance', 'card')", name="payout_to"),
        sa.CheckConstraint(
            "(payout_to = 'card') = (payout_card_id IS NOT NULL)", name="payout_card"
        ),
        sa.CheckConstraint(
            "attention_reason IS NULL OR attention_reason IN ('rolled_back', 'late_deposit')",
            name="attention_reason",
        ),
    )
    op.create_index("ix_sales_user_created", "sales", ["user_id", sa.text("created_at DESC")])
    op.create_index(
        "ix_sales_open",
        "sales",
        ["status", "last_polled_at"],
        postgresql_where=sa.text("status IN ('creating', 'offered', 'hold')"),
    )
    op.create_table(
        "sale_items",
        sa.Column("id", _UUID, primary_key=True),
        _fk("sale_id", "sales.id", ondelete="CASCADE"),
        sa.Column("asset_id", sa.String(32), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("image_url", sa.Text(), nullable=True),
        sa.Column("price_usd", sa.Numeric(14, 6), nullable=False),
        sa.Column("price_uzs", sa.Numeric(14, 0), nullable=False),
        sa.UniqueConstraint("sale_id", "asset_id", name="uq_sale_items_sale_id_asset_id"),
    )


def _requests_settings_checks() -> None:
    op.create_table(
        "payout_requests",
        sa.Column("id", _UUID, primary_key=True),
        _fk("sale_id", "sales.id", ondelete="RESTRICT"),
        _fk("user_id", "users.id", ondelete="RESTRICT"),
        _fk("card_id", "payout_cards.id", ondelete="RESTRICT"),
        sa.Column("amount_uzs", sa.Numeric(14, 0), nullable=False),
        sa.Column("fee_uzs", sa.Numeric(14, 0), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        _at("to_pay_at"),
        _fk("paid_by", "users.id", ondelete="SET NULL", nullable=True),
        _at("paid_at"),
        _at("rejected_at"),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("reject_reason", sa.Text(), nullable=True),
        _ts("created_at"),
        _ts("updated_at"),
        sa.UniqueConstraint("sale_id", name="uq_payout_requests_sale_id"),
        sa.CheckConstraint(f"status IN ({_REQUEST_STATUSES})", name="status"),
    )
    op.create_index("ix_payout_requests_status_due", "payout_requests", ["status", "to_pay_at"])
    op.create_index(
        "ix_payout_requests_user_created",
        "payout_requests",
        ["user_id", sa.text("created_at DESC")],
    )
    op.create_table(
        "sale_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("settings", postgresql.JSONB(), nullable=False),
        _fk("updated_by", "users.id", ondelete="SET NULL", nullable=True),
        _ts("updated_at"),
        sa.CheckConstraint("id = 1", name="singleton"),
    )
    op.create_table(
        "sale_checks",
        sa.Column("id", _UUID, primary_key=True),
        _fk("sale_id", "sales.id", ondelete="CASCADE"),
        _ts("created_at"),
    )
    op.create_index("ix_sale_checks_created_at", "sale_checks", ["created_at"])


def upgrade() -> None:
    """Create the sales tables; let the outbox and the ledger know about sales."""
    _cards()
    _sales()
    _requests_settings_checks()
    op.add_column(
        "email_outbox",
        sa.Column("sale_id", _UUID, sa.ForeignKey("sales.id", ondelete="RESTRICT"), nullable=True),
    )
    op.create_index(
        "uq_email_outbox_sale_kind",
        "email_outbox",
        ["sale_id", "kind"],
        unique=True,
        postgresql_where=sa.text("sale_id IS NOT NULL"),
    )
    op.drop_constraint("kind", "email_outbox", type_="check")
    op.create_check_constraint("kind", "email_outbox", f"kind IN ({_KINDS_NEW})")
    op.drop_constraint("kind", "wallet_accounts", type_="check")
    op.create_check_constraint("kind", "wallet_accounts", f"kind IN ({_ACCOUNTS_NEW})")


def downgrade() -> None:
    """Drop sales (sale letters and ``house_skin_buys`` rows must be gone first)."""
    op.drop_constraint("kind", "wallet_accounts", type_="check")
    op.create_check_constraint("kind", "wallet_accounts", f"kind IN ({_ACCOUNTS_OLD})")
    op.drop_constraint("kind", "email_outbox", type_="check")
    op.create_check_constraint("kind", "email_outbox", f"kind IN ({_KINDS_OLD})")
    op.drop_index("uq_email_outbox_sale_kind", table_name="email_outbox")
    op.drop_column("email_outbox", "sale_id")
    op.drop_index("ix_sale_checks_created_at", table_name="sale_checks")
    op.drop_table("sale_checks")
    op.drop_table("sale_settings")
    op.drop_index("ix_payout_requests_user_created", table_name="payout_requests")
    op.drop_index("ix_payout_requests_status_due", table_name="payout_requests")
    op.drop_table("payout_requests")
    op.drop_table("sale_items")
    op.drop_index("ix_sales_open", table_name="sales")
    op.drop_index("ix_sales_user_created", table_name="sales")
    op.drop_table("sales")
    op.drop_index("ix_payout_cards_user_live", table_name="payout_cards")
    op.drop_table("payout_cards")
