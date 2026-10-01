"""SQLAlchemy ORM for the ``payments`` module (spec §5, rulings R3, R4).

- :class:`WalletTopup` — what the customer pays to fund the balance: a number (``T…``),
  an amount and an expiry. It is a *payable*; the ledger stays in ``wallet``.
- :class:`Payment` — one attempt to pay a payable through one kassa. A top-up has 1..N
  attempts, at most one live (``created``/``pending``) per provider;
  ``wallet_topups.payment_id`` is the attempt that succeeded.

The two tables reference each other: ``payments.topup_id`` (RESTRICT) and
``wallet_topups.payment_id`` (SET NULL, added after both exist — ``use_alter``).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
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
from csmarket.core.ids import new_id

PURPOSES = ("topup", "order")
PAYMENT_STATUSES = ("created", "pending", "succeeded", "failed", "cancelled", "refunded")
TOPUP_STATUSES = ("pending", "succeeded", "expired", "reversed")


def _in(values: tuple[str, ...]) -> str:
    """``('a', 'b')`` as a SQL ``IN`` list."""
    return "(" + ", ".join(f"'{v}'" for v in values) + ")"


class WalletTopup(Base):
    """A balance top-up the customer pays through a kassa."""

    __tablename__ = "wallet_topups"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_id)
    #: ``T`` + 7 Crockford chars (``core.numbers.topup_number``) — the kassa's account value.
    number: Mapped[str] = mapped_column(String(8), nullable=False)
    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id"), nullable=False
    )
    #: Whole soʻm.
    amount_uzs: Mapped[Decimal] = mapped_column(Numeric(14, 0), nullable=False)
    #: The attempt that succeeded; ``NULL`` until one does.
    payment_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("payments.id", ondelete="SET NULL", use_alter=True),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        String(12), nullable=False, server_default=text("'pending'")
    )
    #: The customer's ``Idempotency-Key``; unique per user.
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    succeeded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("number", name="uq_wallet_topups_number"),
        UniqueConstraint(
            "user_id", "idempotency_key", name="uq_wallet_topups_user_id_idempotency_key"
        ),
        # Bare suffixes: the metadata naming convention adds ``ck_wallet_topups_``.
        CheckConstraint("amount_uzs > 0", name="amount_positive"),
        CheckConstraint(f"status IN {_in(TOPUP_STATUSES)}", name="status"),
        Index("ix_wallet_topups_user_created", "user_id", text("created_at DESC")),
        Index(
            "ix_wallet_topups_pending_expires",
            "expires_at",
            postgresql_where=text("status = 'pending'"),
        ),
    )


class Payment(Base):
    """One attempt to pay a payable (a top-up now, an order from M4) through one kassa."""

    __tablename__ = "payments"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_id)
    #: The payable's public number (a top-up's ``T…``, an order's from M4).
    number: Mapped[str] = mapped_column(String(8), nullable=False)
    purpose: Mapped[str] = mapped_column(String(8), nullable=False)
    #: The paid order (M4 adds the foreign key with the ``orders`` table).
    order_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), nullable=True)
    topup_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("wallet_topups.id", ondelete="RESTRICT"), nullable=True
    )
    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id"), nullable=False
    )
    #: Gateway slug: ``click``, ``payme``, ``uzum`` or ``mock``.
    provider: Mapped[str] = mapped_column(String(16), nullable=False)
    #: Our reference at the kassa (``<provider>:<number>``, suffixed on a retry).
    provider_ref: Mapped[str | None] = mapped_column(String(160), nullable=True)
    #: Whole soʻm.
    amount_uzs: Mapped[Decimal] = mapped_column(Numeric(14, 0), nullable=False)
    status: Mapped[str] = mapped_column(
        String(12), nullable=False, server_default=text("'created'")
    )
    idempotency_key: Mapped[str | None] = mapped_column(String(160), nullable=True)
    # Any: a JSON object of scalar values (kassa event ids); never PII.
    extra_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    succeeded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint(f"purpose IN {_in(PURPOSES)}", name="purpose"),
        CheckConstraint(f"status IN {_in(PAYMENT_STATUSES)}", name="status"),
        CheckConstraint("amount_uzs > 0", name="amount_positive"),
        CheckConstraint("(purpose = 'topup') = (topup_id IS NOT NULL)", name="purpose_topup"),
        Index(
            "uq_payments_provider_ref",
            "provider",
            "provider_ref",
            unique=True,
            postgresql_where=text("provider_ref IS NOT NULL"),
        ),
        Index(
            "uq_payments_idempotency_key",
            "idempotency_key",
            unique=True,
            postgresql_where=text("idempotency_key IS NOT NULL"),
        ),
        Index("ix_payments_number", "number"),
        Index("ix_payments_topup", "topup_id"),
        Index("ix_payments_status_created", "status", text("created_at DESC")),
        Index("ix_payments_created", text("created_at DESC"), text("id DESC")),
    )


__all__ = ["PAYMENT_STATUSES", "PURPOSES", "TOPUP_STATUSES", "Payment", "WalletTopup"]
