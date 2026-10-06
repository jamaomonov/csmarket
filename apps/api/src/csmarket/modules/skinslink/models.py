"""SQLAlchemy ORM for the ``skinslink`` module (spec 2026-10-06).

- :class:`SkinslinkItem` — the mirror of Skinslink's CS2 sale list, one row per item (the
  asset id is the key Create Purchase takes), mapped to our catalogue by name and phase.
- :class:`SkinslinkState` — row 1: the events cursor and when the mirror was last synced.
- :class:`SkinslinkPurchase` — the purchase behind one Skinslink order.
- :class:`SkinslinkCheck` — a one-shot queue: "ask Skinslink about purchase N" (from the
  webhook, whose body is never trusted).

Units are Waxpeer's (1000 = $1), so the catalogue prices either source the same way.
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
from csmarket.modules.orders.models import ATTENTION_REASONS

#: ``NOTIFY`` channel the worker listens on for queued purchase checks.
SKINSLINK_CHANNEL = "skinslink"


def _in(values: tuple[str, ...]) -> str:
    """``('a', 'b')`` as a SQL ``IN`` list."""
    return "(" + ", ".join(f"'{v}'" for v in values) + ")"


def _ts() -> Mapped[datetime]:
    """A ``NOT NULL`` timestamp the database fills in."""
    return mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )


def _at() -> Mapped[datetime | None]:
    """A nullable timestamp, stamped when its event happens."""
    return mapped_column(DateTime(timezone=True), nullable=True)


class SkinslinkItem(Base):
    """One item on Skinslink's sale list, as last reported."""

    __tablename__ = "skinslink_items"

    #: Skinslink's item id = the Steam asset id Create Purchase takes.
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    market_hash_name: Mapped[str] = mapped_column(String(255), nullable=False)
    #: Doppler / Gamma Doppler phase; ``''`` for none.
    phase: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("''"))
    #: Skinslink's purchase price, units (1000 = $1).
    price_units: Mapped[int] = mapped_column(BigInteger, nullable=False)
    float_value: Mapped[Decimal | None] = mapped_column(Numeric(7, 6), nullable=True)
    paint_seed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    inspect_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Our catalogue item; ``NULL`` = not in our catalogue (never offered, never priced).
    skin_item_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("skin_items.id", ondelete="SET NULL"), nullable=True
    )
    updated_at: Mapped[datetime] = _ts()

    __table_args__ = (Index("ix_skinslink_items_item_price", "skin_item_id", "price_units"),)


class SkinslinkState(Base):
    """Row 1: the mirror's cursor and freshness."""

    __tablename__ = "skinslink_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    #: Catalogue Events ``next`` (or the full load's ``last_update_at``), kept verbatim.
    cursor: Mapped[str | None] = mapped_column(String(64), nullable=True)
    mirror_synced_at: Mapped[datetime | None] = _at()
    full_loaded_at: Mapped[datetime | None] = _at()

    __table_args__ = (CheckConstraint("id = 1", name="singleton"),)


class SkinslinkPurchase(Base):
    """The Skinslink purchase behind one order."""

    __tablename__ = "skinslink_purchases"

    order_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("orders.id", ondelete="CASCADE"), primary_key=True
    )
    #: Our idempotency key at Skinslink: the order id, ``<order id>:2`` for a substitute.
    merchant_tx_id: Mapped[str] = mapped_column(String(64), nullable=False)
    #: The Skinslink item (Steam asset) being bought.
    asset_id: Mapped[str] = mapped_column(String(32), nullable=False)
    #: The cap we agreed to pay, units.
    paid_units: Mapped[int] = mapped_column(Integer, nullable=False)
    #: Skinslink's purchase id, once an answer names it.
    purchase_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    #: Skinslink's status word (``new`` … ``reverted``); ``NULL`` before any answer.
    status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    #: Steam's trade offer id.
    offer_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    fail_reason: Mapped[str | None] = mapped_column(String(48), nullable=True)
    #: What Skinslink charged, units.
    amount_units: Mapped[int | None] = mapped_column(Integer, nullable=True)
    hold_end_date: Mapped[datetime | None] = _at()
    #: A buy to (re)try on the next tick.
    buy_pending: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false"), default=False
    )
    #: When a buy's answer was lost; resolved by repeating the same ``merchant_tx_id``.
    buy_unconfirmed_at: Mapped[datetime | None] = _at()
    #: One of ``orders.models.ATTENTION_REASONS``; open while ``resolved_at`` is unset.
    attention_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    last_polled_at: Mapped[datetime | None] = _at()
    resolved_at: Mapped[datetime | None] = _at()
    resolved_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    resolved_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = _ts()
    updated_at: Mapped[datetime] = _ts()

    __table_args__ = (
        UniqueConstraint("purchase_id", name="uq_skinslink_purchases_purchase_id"),
        UniqueConstraint("merchant_tx_id", name="uq_skinslink_purchases_merchant_tx_id"),
        CheckConstraint(f"attention_reason IN {_in(ATTENTION_REASONS)}", name="attention_reason"),
    )


class SkinslinkCheck(Base):
    """«Ask Skinslink about purchase N» — one-shot, drained by the worker."""

    __tablename__ = "skinslink_checks"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_id)
    purchase_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = _ts()
    claimed_at: Mapped[datetime | None] = _at()

    __table_args__ = (Index("ix_skinslink_checks_queue", "claimed_at", "created_at"),)


__all__ = [
    "SKINSLINK_CHANNEL",
    "SkinslinkCheck",
    "SkinslinkItem",
    "SkinslinkPurchase",
    "SkinslinkState",
]
