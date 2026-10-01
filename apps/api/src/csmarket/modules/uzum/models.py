"""SQLAlchemy ORM for the ``uzum`` module.

:class:`UzumTransaction` is our own state machine for Uzum's Merchant API — ``CREATED``,
``CONFIRMED``, ``REVERSED``, ``FAILED`` — keyed on ``trans_id`` (Uzum's transaction id) so
every method is replay-safe. Each row backs one payment attempt (``payment_id``) and keeps
the account Uzum sent (``account`` — a top-up number) for statements and admin.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from csmarket.core.db import Base
from csmarket.core.ids import new_id

STATUS_CREATED = "CREATED"
STATUS_CONFIRMED = "CONFIRMED"
STATUS_REVERSED = "REVERSED"
STATUS_FAILED = "FAILED"
UZUM_STATUSES = (STATUS_CREATED, STATUS_CONFIRMED, STATUS_REVERSED, STATUS_FAILED)


class UzumTransaction(Base):
    """One Uzum transaction.

    ``create_time`` / ``confirm_time`` / ``reverse_time`` are ours, in epoch ms; the last
    two stay ``NULL`` until that call lands. ``payment_source`` is what ``/confirm`` sent
    besides the envelope (``paymentSource``, ``tariff``, ``phone``, ``cardType``, …): it
    holds the payer's phone, so it is stored, never logged, and masked in admin.
    """

    __tablename__ = "uzum_transactions"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_id)
    trans_id: Mapped[str] = mapped_column(String(64), nullable=False)
    payment_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("payments.id", ondelete="RESTRICT"), nullable=False
    )
    #: The number Uzum sent as ``params.order`` (a top-up's ``T…``).
    account: Mapped[str] = mapped_column(String(8), nullable=False)
    #: Tiyin, as Uzum charges it (1 soʻm = 100 tiyin).
    amount_tiyin: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    service_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    create_time: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    confirm_time: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    reverse_time: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # Uzum's /confirm extras, free-form JSON by contract (see the class docstring).
    payment_source: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )

    __table_args__ = (
        UniqueConstraint("trans_id", name="uq_uzum_transactions_trans_id"),
        # Bare suffix: the metadata naming convention adds ``ck_uzum_transactions_``.
        CheckConstraint("status IN ('CREATED', 'CONFIRMED', 'REVERSED', 'FAILED')", name="status"),
        Index("ix_uzum_transactions_payment", "payment_id"),
        Index("ix_uzum_transactions_account", "account"),
        # The timeout sweep's scan: stale CREATED rows by age.
        Index(
            "ix_uzum_transactions_created_time",
            "create_time",
            postgresql_where=text("status = 'CREATED'"),
        ),
    )


__all__ = [
    "STATUS_CONFIRMED",
    "STATUS_CREATED",
    "STATUS_FAILED",
    "STATUS_REVERSED",
    "UZUM_STATUSES",
    "UzumTransaction",
]
