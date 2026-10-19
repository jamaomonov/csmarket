"""P2P top-ups: cards, exact-amount reservations, the incoming journal, the settings row
(spec 2026-10-19-p2p-topup; ported by allow-list, ADR-0021).

Check-constraint names are bare suffixes: ``core.db.NAMING_CONVENTION`` adds the
``ck_<table>_`` prefix itself.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from csmarket.core.db import Base
from csmarket.core.ids import new_id

_NOW = text("CURRENT_TIMESTAMP")


class P2PCard(Base):
    """A card buyers transfer to. ``pan_*`` is the sealed full number."""

    __tablename__ = "p2p_cards"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_id)
    label: Mapped[str] = mapped_column(String(64), nullable=False)
    pan_ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    pan_nonce: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    pan_last4: Mapped[str] = mapped_column(String(4), nullable=False)
    holder_name: Mapped[str] = mapped_column(String(128), nullable=False)
    network: Mapped[str] = mapped_column(String(16), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    min_amount_uzs: Mapped[int] = mapped_column(Integer, nullable=False, server_default="10000")
    max_amount_uzs: Mapped[int] = mapped_column(Integer, nullable=False, server_default="5000000")
    daily_limit_uzs: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=_NOW
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=_NOW
    )
    updated_by: Mapped[str | None] = mapped_column(UUID(as_uuid=False), nullable=True)

    __table_args__ = (
        CheckConstraint("network IN ('humo','uzcard')", name="network"),
        CheckConstraint("min_amount_uzs > 0 AND max_amount_uzs >= min_amount_uzs", name="bounds"),
    )


class P2PReservation(Base):
    """An exact amount held on a card for one buyer's top-up, ten minutes."""

    __tablename__ = "p2p_reservations"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_id)
    #: The top-up's number (``T…``).
    number: Mapped[str] = mapped_column(String(8), nullable=False, unique=True)
    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id"), nullable=False
    )
    topup_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("wallet_topups.id"), nullable=False, unique=True
    )
    payment_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("payments.id"), nullable=False, unique=True
    )
    card_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("p2p_cards.id"), nullable=False
    )
    amount_uzs: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="pending")
    holds_amount: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    quarantine_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    incoming_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), nullable=True)

    __table_args__ = (
        CheckConstraint("status IN ('pending','paid','expired','cancelled')", name="status"),
        CheckConstraint("amount_uzs > 0", name="amount"),
        # The rule the whole design rests on: one open amount per card.
        Index(
            "uq_p2p_reservations_open_amount",
            "card_id",
            "amount_uzs",
            unique=True,
            postgresql_where=text("holds_amount"),
        ),
        Index(
            "uq_p2p_reservations_one_pending",
            "user_id",
            unique=True,
            postgresql_where=text("status = 'pending'"),
        ),
        Index("ix_p2p_reservations_sweep", "status", "expires_at"),
        Index("ix_p2p_reservations_user_created", "user_id", "created_at"),
    )


class P2PIncoming(Base):
    """One @HUMOcardbot notification and what it was credited to."""

    __tablename__ = "p2p_incoming"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_id)
    business_connection_id: Mapped[str] = mapped_column(String(128), nullable=False)
    telegram_message_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    amount_uzs: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    source_text: Mapped[str | None] = mapped_column(String(128), nullable=True)
    card_last4: Mapped[str | None] = mapped_column(String(4), nullable=True)
    bank_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    balance_after: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    chain_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    result: Mapped[str] = mapped_column(String(16), nullable=False)
    reservation_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), nullable=True)
    #: Credited by hand to this user (an unmatched transfer, admin «Зачислить»).
    credited_user_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), nullable=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "business_connection_id", "telegram_message_id", name="uq_p2p_incoming_message"
        ),
        CheckConstraint("kind IN ('credit','debit','unparsed')", name="kind"),
        CheckConstraint("result IN ('matched','unmatched','ignored')", name="result"),
        Index("ix_p2p_incoming_card_time", "card_last4", "bank_time"),
        Index("ix_p2p_incoming_received", "received_at"),
    )


class P2PSettings(Base):
    """The single row: the Telegram identities to trust and the buyer's limits. Whether P2P
    is offered at all is the kassa switch (``payments`` settings, ``p2p``)."""

    __tablename__ = "p2p_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    humo_bot_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # The owner's own Telegram id (entered by an admin) and the Business connection Telegram
    # reported for that owner (captured by the intake). Only that connection is read.
    owner_telegram_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    business_connection_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    connection_enabled: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    min_amount_uzs: Mapped[int] = mapped_column(Integer, nullable=False, server_default="10000")
    max_amount_uzs: Mapped[int] = mapped_column(Integer, nullable=False, server_default="5000000")
    daily_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="3")
    daily_amount_uzs: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default="10000000"
    )
    last_received_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    updated_by: Mapped[str | None] = mapped_column(UUID(as_uuid=False), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=_NOW
    )

    __table_args__ = (
        CheckConstraint("id = 1", name="singleton"),
        CheckConstraint(
            "min_amount_uzs > 0 AND max_amount_uzs >= min_amount_uzs AND daily_count > 0"
            " AND daily_amount_uzs >= max_amount_uzs",
            name="limits",
        ),
    )


__all__ = ["P2PCard", "P2PIncoming", "P2PReservation", "P2PSettings"]
