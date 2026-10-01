"""payme: payme_transactions (Payme Merchant API)

Revision ID: 0009_payme_transactions
Revises: 0008_click_transactions
Create Date: 2026-10-01
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009_payme_transactions"
down_revision: str | None = "0008_click_transactions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _ts(name: str) -> sa.Column[object]:
    return sa.Column(
        name,
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("CURRENT_TIMESTAMP"),
    )


def _epoch_ms(name: str) -> sa.Column[object]:
    return sa.Column(name, sa.BigInteger(), nullable=False, server_default=sa.text("0"))


def upgrade() -> None:
    op.create_table(
        "payme_transactions",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("payme_id", sa.String(64), nullable=False),
        sa.Column(
            "payment_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("payments.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("account", sa.String(8), nullable=False),
        sa.Column("amount_tiyin", sa.BigInteger(), nullable=False),
        sa.Column("state", sa.Integer(), nullable=False),
        sa.Column("reason", sa.Integer(), nullable=True),
        _epoch_ms("create_time"),
        _epoch_ms("perform_time"),
        _epoch_ms("cancel_time"),
        sa.Column(
            "fiscal_data",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        _ts("created_at"),
        _ts("updated_at"),
        sa.UniqueConstraint("payme_id", name="uq_payme_transactions_payme_id"),
        # Bare suffix: the metadata naming convention adds ``ck_payme_transactions_``.
        sa.CheckConstraint("state IN (1, 2, -1, -2)", name="state"),
    )
    op.create_index("ix_payme_transactions_payment", "payme_transactions", ["payment_id"])
    op.create_index("ix_payme_transactions_account", "payme_transactions", ["account"])
    op.create_index(
        "ix_payme_transactions_state_create", "payme_transactions", ["state", "create_time"]
    )


def downgrade() -> None:
    op.drop_index("ix_payme_transactions_state_create", table_name="payme_transactions")
    op.drop_index("ix_payme_transactions_account", table_name="payme_transactions")
    op.drop_index("ix_payme_transactions_payment", table_name="payme_transactions")
    op.drop_table("payme_transactions")
