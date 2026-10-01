"""payments: wallet_topups and payments (spec §5, rulings R3, R4)

The two tables reference each other: ``wallet_topups`` is created first without its
``payment_id`` foreign key, then ``payments`` (which points at ``wallet_topups``), then
the ``wallet_topups.payment_id → payments.id`` key is added. Downgrade in reverse.

Revision ID: 0007_payments_topups
Revises: 0006_wallet_ledger
Create Date: 2026-10-01
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007_payments_topups"
down_revision: str | None = "0006_wallet_ledger"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TOPUP_PAYMENT_FK = "fk_wallet_topups_payment_id_payments"


def _ts(name: str) -> sa.Column[object]:
    return sa.Column(
        name,
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("CURRENT_TIMESTAMP"),
    )


def _create_wallet_topups() -> None:
    op.create_table(
        "wallet_topups",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("number", sa.String(8), nullable=False),
        sa.Column(
            "user_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column("amount_uzs", sa.Numeric(14, 0), nullable=False),
        sa.Column("payment_id", postgresql.UUID(as_uuid=False), nullable=True),
        sa.Column("status", sa.String(12), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("idempotency_key", sa.String(160), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        _ts("created_at"),
        sa.Column("succeeded_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("number", name="uq_wallet_topups_number"),
        sa.UniqueConstraint(
            "user_id", "idempotency_key", name="uq_wallet_topups_user_id_idempotency_key"
        ),
        # Bare suffixes: the metadata naming convention adds the ``ck_wallet_topups_`` prefix.
        sa.CheckConstraint("amount_uzs > 0", name="amount_positive"),
        sa.CheckConstraint(
            "status IN ('pending', 'succeeded', 'expired', 'reversed')", name="status"
        ),
    )
    op.create_index(
        "ix_wallet_topups_user_created", "wallet_topups", ["user_id", sa.text("created_at DESC")]
    )
    op.create_index(
        "ix_wallet_topups_pending_expires",
        "wallet_topups",
        ["expires_at"],
        postgresql_where=sa.text("status = 'pending'"),
    )


def _create_payments() -> None:
    op.create_table(
        "payments",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("number", sa.String(8), nullable=False),
        sa.Column("purpose", sa.String(8), nullable=False),
        sa.Column("order_id", postgresql.UUID(as_uuid=False), nullable=True),
        sa.Column(
            "topup_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("wallet_topups.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "user_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column("provider", sa.String(16), nullable=False),
        sa.Column("provider_ref", sa.String(160), nullable=True),
        sa.Column("amount_uzs", sa.Numeric(14, 0), nullable=False),
        sa.Column("status", sa.String(12), nullable=False, server_default=sa.text("'created'")),
        sa.Column("idempotency_key", sa.String(160), nullable=True),
        sa.Column(
            "metadata", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        _ts("created_at"),
        _ts("updated_at"),
        sa.Column("succeeded_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("purpose IN ('topup', 'order')", name="purpose"),
        sa.CheckConstraint(
            "status IN ('created', 'pending', 'succeeded', 'failed', 'cancelled', 'refunded')",
            name="status",
        ),
        sa.CheckConstraint("amount_uzs > 0", name="amount_positive"),
        sa.CheckConstraint("(purpose = 'topup') = (topup_id IS NOT NULL)", name="purpose_topup"),
    )
    op.create_index(
        "uq_payments_provider_ref",
        "payments",
        ["provider", "provider_ref"],
        unique=True,
        postgresql_where=sa.text("provider_ref IS NOT NULL"),
    )
    op.create_index(
        "uq_payments_idempotency_key",
        "payments",
        ["idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )
    op.create_index("ix_payments_number", "payments", ["number"])
    op.create_index("ix_payments_topup", "payments", ["topup_id"])
    op.create_index(
        "ix_payments_status_created", "payments", ["status", sa.text("created_at DESC")]
    )
    op.create_index(
        "ix_payments_created", "payments", [sa.text("created_at DESC"), sa.text("id DESC")]
    )


def upgrade() -> None:
    _create_wallet_topups()
    _create_payments()
    op.create_foreign_key(
        _TOPUP_PAYMENT_FK,
        "wallet_topups",
        "payments",
        ["payment_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(_TOPUP_PAYMENT_FK, "wallet_topups", type_="foreignkey")
    for index in (
        "ix_payments_created",
        "ix_payments_status_created",
        "ix_payments_topup",
        "ix_payments_number",
        "uq_payments_idempotency_key",
        "uq_payments_provider_ref",
    ):
        op.drop_index(index, table_name="payments")
    op.drop_table("payments")
    op.drop_index("ix_wallet_topups_pending_expires", table_name="wallet_topups")
    op.drop_index("ix_wallet_topups_user_created", table_name="wallet_topups")
    op.drop_table("wallet_topups")
