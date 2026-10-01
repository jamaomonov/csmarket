"""SQLAlchemy ORM for the ``payme`` module.

:class:`PaymeTransaction` mirrors Payme's own transaction record: state ``1`` (created),
``2`` (performed), ``-1`` (cancelled before perform), ``-2`` (cancelled after perform).
It is keyed on ``payme_id`` (Payme's transaction id) so every Merchant API method is
idempotent against replays. Each row backs one payment attempt (``payment_id``) and keeps
the account Payme sent (``account`` — a top-up number) for statements and admin.
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
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from csmarket.core.db import Base
from csmarket.core.ids import new_id

#: Payme's transaction states.
STATE_CREATED, STATE_PERFORMED = 1, 2
STATE_CANCELLED, STATE_CANCELLED_AFTER_PERFORM = -1, -2
PAYME_STATES = (STATE_CREATED, STATE_PERFORMED, STATE_CANCELLED, STATE_CANCELLED_AFTER_PERFORM)


class PaymeTransaction(Base):
    """One Payme transaction.

    ``create_time`` is Payme's own ``time`` (epoch ms) from ``CreateTransaction``;
    ``perform_time`` / ``cancel_time`` are ours, in epoch ms. All three are ``0`` until
    set and are echoed back verbatim by ``CheckTransaction`` and ``GetStatement``.
    """

    __tablename__ = "payme_transactions"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_id)
    payme_id: Mapped[str] = mapped_column(String(64), nullable=False)
    payment_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("payments.id", ondelete="RESTRICT"), nullable=False
    )
    #: The number Payme sent as ``account.order`` (a top-up's ``T…``).
    account: Mapped[str] = mapped_column(String(8), nullable=False)
    #: Tiyin, as Payme charges it (1 soʻm = 100 tiyin).
    amount_tiyin: Mapped[int] = mapped_column(BigInteger, nullable=False)
    state: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[int | None] = mapped_column(Integer, nullable=True)
    create_time: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    perform_time: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    cancel_time: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    # Payme's receipt payloads keyed by type (PERFORM / CANCEL); free-form JSON by contract.
    fiscal_data: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )

    __table_args__ = (
        UniqueConstraint("payme_id", name="uq_payme_transactions_payme_id"),
        # Bare suffix: the metadata naming convention adds ``ck_payme_transactions_``.
        CheckConstraint("state IN (1, 2, -1, -2)", name="state"),
        Index("ix_payme_transactions_payment", "payment_id"),
        Index("ix_payme_transactions_account", "account"),
        # The timeout sweep's scan (state 1 by age) and GetStatement's window.
        Index("ix_payme_transactions_state_create", "state", "create_time"),
    )


__all__ = [
    "PAYME_STATES",
    "STATE_CANCELLED",
    "STATE_CANCELLED_AFTER_PERFORM",
    "STATE_CREATED",
    "STATE_PERFORMED",
    "PaymeTransaction",
]
