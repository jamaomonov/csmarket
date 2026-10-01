"""wallet ledger: wallet_accounts, wallet_transactions, wallet_postings (spec §5, R1)

UZS only — no currency column; amounts are whole soʻm, ``numeric(14,0)``.

Revision ID: 0006_wallet_ledger
Revises: 0005_admin_audit_log
Create Date: 2026-10-01
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006_wallet_ledger"
down_revision: str | None = "0005_admin_audit_log"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _created_at() -> sa.Column[object]:
    return sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("CURRENT_TIMESTAMP"),
    )


def upgrade() -> None:
    op.create_table(
        "wallet_accounts",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("owner_type", sa.String(16), nullable=False),
        sa.Column("owner_id", sa.String(64), nullable=False),
        sa.Column("kind", sa.String(48), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default=sa.text("'active'")),
        _created_at(),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.UniqueConstraint(
            "owner_type", "owner_id", "kind", name="uq_wallet_accounts_owner_type_owner_id_kind"
        ),
        # Bare suffixes: the metadata naming convention adds the ``ck_wallet_accounts_`` prefix.
        sa.CheckConstraint("owner_type IN ('user', 'house', 'provider')", name="owner_type"),
        sa.CheckConstraint(
            "kind IN ('user_wallet', 'provider_clearing', 'house_payments_received', "
            "'house_adjustments')",
            name="kind",
        ),
        sa.CheckConstraint("status IN ('active', 'frozen')", name="status"),
    )
    op.create_index(
        "ix_wallet_accounts_user_wallet",
        "wallet_accounts",
        ["owner_id"],
        postgresql_where=sa.text("kind = 'user_wallet' AND owner_type = 'user'"),
    )

    op.create_table(
        "wallet_transactions",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("kind", sa.String(48), nullable=False),
        sa.Column("reference_type", sa.String(32), nullable=True),
        sa.Column("reference_id", sa.String(64), nullable=True),
        sa.Column("idempotency_key", sa.String(160), nullable=False),
        sa.Column("actor", sa.String(64), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        _created_at(),
        sa.UniqueConstraint("idempotency_key", name="uq_wallet_transactions_idempotency_key"),
    )
    op.create_index(
        "ix_wallet_transactions_reference",
        "wallet_transactions",
        ["reference_type", "reference_id"],
    )

    op.create_table(
        "wallet_postings",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "transaction_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("wallet_transactions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "account_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("wallet_accounts.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("direction", sa.CHAR(1), nullable=False),
        sa.Column("amount", sa.Numeric(14, 0), nullable=False),
        _created_at(),
        sa.CheckConstraint("direction IN ('D', 'C')", name="direction"),
        sa.CheckConstraint("amount > 0", name="amount_positive"),
    )
    op.create_index(
        "ix_wallet_postings_account_created",
        "wallet_postings",
        ["account_id", sa.text("created_at DESC")],
    )
    op.create_index("ix_wallet_postings_transaction", "wallet_postings", ["transaction_id"])


def downgrade() -> None:
    op.drop_index("ix_wallet_postings_transaction", table_name="wallet_postings")
    op.drop_index("ix_wallet_postings_account_created", table_name="wallet_postings")
    op.drop_table("wallet_postings")
    op.drop_index("ix_wallet_transactions_reference", table_name="wallet_transactions")
    op.drop_table("wallet_transactions")
    op.drop_index("ix_wallet_accounts_user_wallet", table_name="wallet_accounts")
    op.drop_table("wallet_accounts")
