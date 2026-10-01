"""SQLAlchemy ORM for the ``wallet`` module — the double-entry ledger (spec §5, ruling R1).

- :class:`WalletAccount` — one account per ``(owner_type, owner_id, kind)``.
- :class:`WalletTransaction` — one business event, unique by ``idempotency_key``.
- :class:`WalletPosting` — the debit/credit legs of a transaction; ``SUM(D) == SUM(C)``.

UZS only: there is no currency column, amounts are whole soʻm (``numeric(14,0)``).
Written only by :mod:`csmarket.modules.wallet.service`.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    CHAR,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from csmarket.core.db import Base

#: Who may own an account (ruling R2).
OWNER_TYPES = ("user", "house", "provider")
#: Account kinds (ruling R2); their normal sides live in ``service.NORMAL_SIDE``.
ACCOUNT_KINDS = ("user_wallet", "provider_clearing", "house_payments_received", "house_adjustments")
ACCOUNT_STATUSES = ("active", "frozen")


def _in(values: tuple[str, ...]) -> str:
    """``('a', 'b')`` as a SQL ``IN`` list."""
    return "(" + ", ".join(f"'{v}'" for v in values) + ")"


class WalletAccount(Base):
    """One ledger account; ``(owner_type, owner_id, kind)`` is unique."""

    __tablename__ = "wallet_accounts"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    owner_type: Mapped[str] = mapped_column(String(16), nullable=False)
    #: A user id, a provider slug (``click``, ``payme``, ``uzum``) or ``house``.
    owner_id: Mapped[str] = mapped_column(String(64), nullable=False)
    kind: Mapped[str] = mapped_column(String(48), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'active'"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )

    __table_args__ = (
        UniqueConstraint(
            "owner_type", "owner_id", "kind", name="uq_wallet_accounts_owner_type_owner_id_kind"
        ),
        # Bare suffixes: the metadata naming convention adds ``ck_wallet_accounts_``.
        CheckConstraint(f"owner_type IN {_in(OWNER_TYPES)}", name="owner_type"),
        CheckConstraint(f"kind IN {_in(ACCOUNT_KINDS)}", name="kind"),
        CheckConstraint(f"status IN {_in(ACCOUNT_STATUSES)}", name="status"),
        Index(
            "ix_wallet_accounts_user_wallet",
            "owner_id",
            postgresql_where=text("kind = 'user_wallet' AND owner_type = 'user'"),
        ),
    )


class WalletTransaction(Base):
    """One business event (a top-up, its reversal, an admin adjustment) and its key."""

    __tablename__ = "wallet_transactions"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    kind: Mapped[str] = mapped_column(String(48), nullable=False)
    reference_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    reference_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    #: One per business event (``topup:{topup_id}``, …) — a replay returns this row.
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    actor: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Any: a JSON object of scalar values; never PII.
    extra_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )

    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_wallet_transactions_idempotency_key"),
        Index("ix_wallet_transactions_reference", "reference_type", "reference_id"),
    )


class WalletPosting(Base):
    """One leg of a transaction. Append-only: never updated, deleted only by CASCADE."""

    __tablename__ = "wallet_postings"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    transaction_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("wallet_transactions.id", ondelete="CASCADE"),
        nullable=False,
    )
    account_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("wallet_accounts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    direction: Mapped[str] = mapped_column(CHAR(1), nullable=False)
    #: Whole soʻm.
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 0), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )

    __table_args__ = (
        CheckConstraint("direction IN ('D', 'C')", name="direction"),
        CheckConstraint("amount > 0", name="amount_positive"),
        Index("ix_wallet_postings_account_created", "account_id", text("created_at DESC")),
        Index("ix_wallet_postings_transaction", "transaction_id"),
    )


__all__ = [
    "ACCOUNT_KINDS",
    "ACCOUNT_STATUSES",
    "OWNER_TYPES",
    "WalletAccount",
    "WalletPosting",
    "WalletTransaction",
]
