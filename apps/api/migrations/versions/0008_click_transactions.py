"""click: click_transactions (Click Shop API prepare / complete)

Revision ID: 0008_click_transactions
Revises: 0007_payments_topups
Create Date: 2026-10-01
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008_click_transactions"
down_revision: str | None = "0007_payments_topups"
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
        "click_transactions",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("merchant_prepare_id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("click_trans_id", sa.BigInteger(), nullable=False),
        sa.Column("service_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "payment_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("payments.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("account", sa.String(8), nullable=False),
        sa.Column("amount", sa.Numeric(14, 0), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("click_paydoc_id", sa.BigInteger(), nullable=True),
        sa.Column("prepare_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("complete_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancel_time", sa.DateTime(timezone=True), nullable=True),
        _ts("created_at"),
        _ts("updated_at"),
        sa.UniqueConstraint(
            "merchant_prepare_id", name="uq_click_transactions_merchant_prepare_id"
        ),
        sa.UniqueConstraint(
            "click_trans_id", "service_id", name="uq_click_transactions_trans_service"
        ),
        # Bare suffix: the metadata naming convention adds ``ck_click_transactions_``.
        sa.CheckConstraint("status IN ('PREPARED', 'CONFIRMED', 'CANCELLED')", name="status"),
    )
    op.create_index("ix_click_transactions_payment", "click_transactions", ["payment_id"])
    op.create_index("ix_click_transactions_account", "click_transactions", ["account"])
    op.create_index(
        "ix_click_transactions_prepared_time",
        "click_transactions",
        ["prepare_time"],
        postgresql_where=sa.text("status = 'PREPARED'"),
    )


def downgrade() -> None:
    op.drop_index("ix_click_transactions_prepared_time", table_name="click_transactions")
    op.drop_index("ix_click_transactions_account", table_name="click_transactions")
    op.drop_index("ix_click_transactions_payment", table_name="click_transactions")
    op.drop_table("click_transactions")
