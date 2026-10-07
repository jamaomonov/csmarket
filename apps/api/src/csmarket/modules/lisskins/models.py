"""SQLAlchemy ORM for the ``lisskins`` module (spec 2026-10-07).

- :class:`LisskinsOffer` — the 10 cheapest instant lots of each catalogue item, from the
  public export (``lisskins.snapshot``); ``id`` is LIS-SKINS' skin id, what ``market/buy``
  takes.
- :class:`LisskinsState` — row 1: when the export was made, when we applied it, how many
  sellable lots it had.
- :class:`LisskinsPurchase` — the purchase behind one LIS-SKINS order.

Units are 1000 = $1, as every source's.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

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
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from csmarket.core.db import Base
from csmarket.modules.orders.models import ATTENTION_REASONS


def _in(values: tuple[str, ...]) -> str:
    """``('a', 'b')`` as a SQL ``IN`` list."""
    return "(" + ", ".join(f"'{v}'" for v in values) + ")"


def _ts() -> Mapped[datetime]:
    return mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )


def _at() -> Mapped[datetime | None]:
    return mapped_column(DateTime(timezone=True), nullable=True)


class LisskinsOffer(Base):
    """One of the 10 cheapest instant lots of a catalogue item."""

    __tablename__ = "lisskins_offers"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    skin_item_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("skin_items.id", ondelete="CASCADE"), nullable=False
    )
    price_units: Mapped[int] = mapped_column(BigInteger, nullable=False)
    float_value: Mapped[Decimal | None] = mapped_column(Numeric(7, 6), nullable=True)
    paint_seed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: The Steam asset id (``item_asset_id``).
    asset_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    inspect_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Any: ``[{"name": str, "image": str | None, "slot": int | None, "wear": float | None}]``
    # as LIS-SKINS names them (``export.Sticker``).
    stickers: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb"), default=list
    )
    updated_at: Mapped[datetime] = _ts()

    __table_args__ = (Index("ix_lisskins_offers_item_price", "skin_item_id", "price_units"),)


class LisskinsState(Base):
    """Row 1: the snapshot's freshness and size."""

    __tablename__ = "lisskins_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    #: The export's own ``last_update`` — what freshness is judged by.
    snapshot_at: Mapped[datetime | None] = _at()
    synced_at: Mapped[datetime | None] = _at()
    #: Sellable lots in the last applied export (a tick with under half of it is refused).
    lots: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"), default=0)

    __table_args__ = (CheckConstraint("id = 1", name="singleton"),)


class LisskinsPurchase(Base):
    """The LIS-SKINS purchase behind one order."""

    __tablename__ = "lisskins_purchases"

    order_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("orders.id", ondelete="CASCADE"), primary_key=True
    )
    #: Our idempotency key at LIS-SKINS: the order id, ``<order id>:2`` for a substitute.
    custom_id: Mapped[str] = mapped_column(String(64), nullable=False)
    #: The LIS-SKINS lot being bought.
    skin_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    #: The cap we agreed to pay, units.
    paid_units: Mapped[int] = mapped_column(Integer, nullable=False)
    purchase_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    #: The skin's status word (``processing`` … ``return``); ``NULL`` before any answer.
    status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    return_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    error: Mapped[str | None] = mapped_column(String(32), nullable=True)
    steam_trade_offer_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    offer_expiry_at: Mapped[datetime | None] = _at()
    #: What LIS-SKINS charged, units.
    amount_units: Mapped[int | None] = mapped_column(Integer, nullable=True)
    buy_pending: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false"), default=False
    )
    #: When a buy's answer was lost; resolved by ``market/info`` (``lisskins_reconcile``).
    buy_unconfirmed_at: Mapped[datetime | None] = _at()
    attention_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    last_polled_at: Mapped[datetime | None] = _at()
    resolved_at: Mapped[datetime | None] = _at()
    resolved_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    resolved_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = _ts()
    updated_at: Mapped[datetime] = _ts()

    __table_args__ = (
        UniqueConstraint("custom_id", name="uq_lisskins_purchases_custom_id"),
        CheckConstraint(f"attention_reason IN {_in(ATTENTION_REASONS)}", name="attention_reason"),
    )


__all__ = ["LisskinsOffer", "LisskinsPurchase", "LisskinsState"]
