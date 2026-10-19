"""p2p: cards, reservations, the incoming journal and the settings row

Spec 2026-10-19-p2p-topup. A buyer's balance top-up by a card transfer, matched from the HUMO
bot's Telegram notification by card last4 + exact amount.

Revision ID: 0038_p2p
Revises: 0037_sales_credited_at
Create Date: 2026-10-19
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0038_p2p"
down_revision: str | None = "0037_sales_credited_at"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UUID = postgresql.UUID(as_uuid=False)
_TS = sa.DateTime(timezone=True)
_NOW = sa.text("CURRENT_TIMESTAMP")


def upgrade() -> None:
    """Create the four tables."""
    op.create_table(
        "p2p_cards",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column("label", sa.String(64), nullable=False),
        sa.Column("pan_ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("pan_nonce", sa.LargeBinary(), nullable=False),
        sa.Column("pan_last4", sa.String(4), nullable=False),
        sa.Column("holder_name", sa.String(128), nullable=False),
        sa.Column("network", sa.String(16), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("min_amount_uzs", sa.Integer(), nullable=False, server_default="10000"),
        sa.Column("max_amount_uzs", sa.Integer(), nullable=False, server_default="5000000"),
        sa.Column("daily_limit_uzs", sa.BigInteger(), nullable=True),
        sa.Column("created_at", _TS, nullable=False, server_default=_NOW),
        sa.Column("updated_at", _TS, nullable=False, server_default=_NOW),
        sa.Column("updated_by", _UUID, nullable=True),
        sa.CheckConstraint("network IN ('humo','uzcard')", name="network"),
        sa.CheckConstraint(
            "min_amount_uzs > 0 AND max_amount_uzs >= min_amount_uzs", name="bounds"
        ),
    )
    op.create_table(
        "p2p_reservations",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column("number", sa.String(8), nullable=False, unique=True),
        sa.Column("user_id", _UUID, sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "topup_id", _UUID, sa.ForeignKey("wallet_topups.id"), nullable=False, unique=True
        ),
        sa.Column("payment_id", _UUID, sa.ForeignKey("payments.id"), nullable=False, unique=True),
        sa.Column("card_id", _UUID, sa.ForeignKey("p2p_cards.id"), nullable=False),
        sa.Column("amount_uzs", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("holds_amount", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", _TS, nullable=False),
        sa.Column("expires_at", _TS, nullable=False),
        sa.Column("closed_at", _TS, nullable=True),
        sa.Column("quarantine_until", _TS, nullable=True),
        sa.Column("incoming_id", _UUID, nullable=True),
        sa.CheckConstraint("status IN ('pending','paid','expired','cancelled')", name="status"),
        sa.CheckConstraint("amount_uzs > 0", name="amount"),
    )
    op.create_index(
        "uq_p2p_reservations_open_amount",
        "p2p_reservations",
        ["card_id", "amount_uzs"],
        unique=True,
        postgresql_where=sa.text("holds_amount"),
    )
    op.create_index(
        "uq_p2p_reservations_one_pending",
        "p2p_reservations",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index("ix_p2p_reservations_sweep", "p2p_reservations", ["status", "expires_at"])
    op.create_index(
        "ix_p2p_reservations_user_created", "p2p_reservations", ["user_id", "created_at"]
    )
    op.create_table(
        "p2p_incoming",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column("business_connection_id", sa.String(128), nullable=False),
        sa.Column("telegram_message_id", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("amount_uzs", sa.Numeric(18, 2), nullable=True),
        sa.Column("source_text", sa.String(128), nullable=True),
        sa.Column("card_last4", sa.String(4), nullable=True),
        sa.Column("bank_time", _TS, nullable=True),
        sa.Column("balance_after", sa.Numeric(18, 2), nullable=True),
        sa.Column("chain_ok", sa.Boolean(), nullable=True),
        sa.Column("raw_text", sa.Text(), nullable=False),
        sa.Column("result", sa.String(16), nullable=False),
        sa.Column("reservation_id", _UUID, nullable=True),
        sa.Column("credited_user_id", _UUID, nullable=True),
        sa.Column("received_at", _TS, nullable=False),
        sa.UniqueConstraint(
            "business_connection_id", "telegram_message_id", name="uq_p2p_incoming_message"
        ),
        sa.CheckConstraint("kind IN ('credit','debit','unparsed')", name="kind"),
        sa.CheckConstraint("result IN ('matched','unmatched','ignored')", name="result"),
    )
    op.create_index("ix_p2p_incoming_card_time", "p2p_incoming", ["card_last4", "bank_time"])
    op.create_index("ix_p2p_incoming_received", "p2p_incoming", ["received_at"])
    op.create_table(
        "p2p_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("humo_bot_user_id", sa.BigInteger(), nullable=True),
        sa.Column("owner_telegram_user_id", sa.BigInteger(), nullable=True),
        sa.Column("business_connection_id", sa.String(128), nullable=True),
        sa.Column("connection_enabled", sa.Boolean(), nullable=True),
        sa.Column("min_amount_uzs", sa.Integer(), nullable=False, server_default="10000"),
        sa.Column("max_amount_uzs", sa.Integer(), nullable=False, server_default="5000000"),
        sa.Column("daily_count", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("daily_amount_uzs", sa.BigInteger(), nullable=False, server_default="10000000"),
        sa.Column("last_received_at", _TS, nullable=True),
        sa.Column("updated_by", _UUID, nullable=True),
        sa.Column("updated_at", _TS, nullable=False, server_default=_NOW),
        sa.CheckConstraint("id = 1", name="singleton"),
        sa.CheckConstraint(
            "min_amount_uzs > 0 AND max_amount_uzs >= min_amount_uzs AND daily_count > 0"
            " AND daily_amount_uzs >= max_amount_uzs",
            name="limits",
        ),
    )


def downgrade() -> None:
    """Drop the four tables."""
    op.drop_table("p2p_settings")
    op.drop_index("ix_p2p_incoming_received", table_name="p2p_incoming")
    op.drop_index("ix_p2p_incoming_card_time", table_name="p2p_incoming")
    op.drop_table("p2p_incoming")
    op.drop_index("ix_p2p_reservations_user_created", table_name="p2p_reservations")
    op.drop_index("ix_p2p_reservations_sweep", table_name="p2p_reservations")
    op.drop_index("uq_p2p_reservations_one_pending", table_name="p2p_reservations")
    op.drop_index("uq_p2p_reservations_open_amount", table_name="p2p_reservations")
    op.drop_table("p2p_reservations")
    op.drop_table("p2p_cards")
