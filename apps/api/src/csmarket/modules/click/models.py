"""SQLAlchemy ORM for the ``click`` module.

:class:`ClickTransaction` is the source of truth for Click's Shop API state machine:
``PREPARED`` → ``CONFIRMED`` | ``CANCELLED``. ``/prepare`` is idempotent on
``(click_trans_id, service_id)``; ``/complete`` finds the row by the ``merchant_prepare_id``
we handed Click at prepare time. Each row backs one payment attempt (``payment_id``) and
keeps the account Click sent (``account`` — a top-up number) for statements and admin.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from csmarket.core.db import Base
from csmarket.core.ids import new_id

CLICK_STATUSES = ("PREPARED", "CONFIRMED", "CANCELLED")


class ClickTransaction(Base):
    """One Click Shop API transaction.

    ``merchant_prepare_id`` is a DB-generated (IDENTITY) integer: Click's prepare answer
    needs an integer id, so this column exists to hand Click one. ``prepare_time`` /
    ``complete_time`` / ``cancel_time`` are stamped on each transition.
    """

    __tablename__ = "click_transactions"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_id)
    merchant_prepare_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), nullable=False, unique=True
    )
    click_trans_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    service_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    payment_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("payments.id", ondelete="RESTRICT"), nullable=False
    )
    #: The number Click sent as ``merchant_trans_id`` (a top-up's ``T…``).
    account: Mapped[str] = mapped_column(String(8), nullable=False)
    #: Whole soʻm, as Click charges it.
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 0), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    click_paydoc_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    prepare_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    complete_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )

    __table_args__ = (
        UniqueConstraint(
            "click_trans_id", "service_id", name="uq_click_transactions_trans_service"
        ),
        # Bare suffix: the metadata naming convention adds ``ck_click_transactions_``.
        CheckConstraint("status IN ('PREPARED', 'CONFIRMED', 'CANCELLED')", name="status"),
        Index("ix_click_transactions_payment", "payment_id"),
        Index("ix_click_transactions_account", "account"),
        # The timeout sweep's scan: stale PREPARED rows by age.
        Index(
            "ix_click_transactions_prepared_time",
            "prepare_time",
            postgresql_where=text("status = 'PREPARED'"),
        ),
    )


__all__ = ["CLICK_STATUSES", "ClickTransaction"]
