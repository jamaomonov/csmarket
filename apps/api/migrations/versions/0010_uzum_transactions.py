"""uzum: uzum_transactions (Uzum Bank Merchant API)

Revision ID: 0010_uzum_transactions
Revises: 0009_payme_transactions
Create Date: 2026-10-01
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010_uzum_transactions"
down_revision: str | None = "0009_payme_transactions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _ts(name: str) -> sa.Column[object]:
    return sa.Column(
        name,
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("CURRENT_TIMESTAMP"),
    )


def upgrade() -> None:
    op.create_table(
        "uzum_transactions",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("trans_id", sa.String(64), nullable=False),
        sa.Column(
            "payment_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("payments.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("account", sa.String(8), nullable=False),
        sa.Column("amount_tiyin", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("service_id", sa.BigInteger(), nullable=True),
        sa.Column("create_time", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column("confirm_time", sa.BigInteger(), nullable=True),
        sa.Column("reverse_time", sa.BigInteger(), nullable=True),
        sa.Column(
            "payment_source",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        _ts("created_at"),
        _ts("updated_at"),
        sa.UniqueConstraint("trans_id", name="uq_uzum_transactions_trans_id"),
        # Bare suffix: the metadata naming convention adds ``ck_uzum_transactions_``.
        sa.CheckConstraint(
            "status IN ('CREATED', 'CONFIRMED', 'REVERSED', 'FAILED')", name="status"
        ),
    )
    op.create_index("ix_uzum_transactions_payment", "uzum_transactions", ["payment_id"])
    op.create_index("ix_uzum_transactions_account", "uzum_transactions", ["account"])
    op.create_index(
        "ix_uzum_transactions_created_time",
        "uzum_transactions",
        ["create_time"],
        postgresql_where=sa.text("status = 'CREATED'"),
    )


def downgrade() -> None:
    op.drop_index("ix_uzum_transactions_created_time", table_name="uzum_transactions")
    op.drop_index("ix_uzum_transactions_account", table_name="uzum_transactions")
    op.drop_index("ix_uzum_transactions_payment", table_name="uzum_transactions")
    op.drop_table("uzum_transactions")
