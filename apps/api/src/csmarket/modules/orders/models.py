"""SQLAlchemy ORM for the ``orders`` module (spec §5, rulings R1–R3).

- :class:`Order` — one skin bought by one customer: the offer chosen at checkout, the price
  billed in soʻm and the Waxpeer cost behind it, the trade-link snapshot, and the status the
  FSM (:mod:`csmarket.modules.orders.fsm`) moves. The table is also the worker's queue
  (``claimed_at`` / ``claimed_by`` / ``next_check_at``).
- :class:`SkinTrade` — the purchase at Waxpeer and the Steam trade behind an order, one per
  order (``project_id`` = the order id, so a buy can be looked up and never repeated).

Money: soʻm ``numeric(14,0)``, USD ``numeric(12,6)``, Waxpeer units integers (1000 = $1).
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
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from csmarket.core.db import Base
from csmarket.core.ids import new_id

ORDER_STATUSES = (
    "pending",
    "paid",
    "buying",
    "trade_sent",
    "delivered",
    "cancelled",
    "failed",
    "returned",
)
#: Statuses an order never leaves.
TERMINAL: frozenset[str] = frozenset({"delivered", "cancelled", "failed", "returned"})
#: Paid, not yet settled: the money is ours and the skin is on its way (no refund now).
IN_FLIGHT: frozenset[str] = frozenset({"paid", "buying", "trade_sent"})
#: Why a trade waits for an admin (ruling R3); ``NULL`` when it does not.
ATTENTION_REASONS = (
    "buy_unconfirmed",
    "ambiguous_trade",
    "rolled_back",
    "waxpeer_forbidden",
    "audit_divergence",
)
#: ``orders.failure_reason`` codes.
FAILURE_REASONS = ("sold_out", "waxpeer_low_balance", "invalid_trade_link", "not_accepted", "admin")
#: Where a refund goes (spec §7.8: the balance only).
REFUND_TARGETS = ("balance",)


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


class Order(Base):
    """One skin bought by one customer."""

    __tablename__ = "orders"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_id)
    #: 8 Crockford chars (``core.numbers.order_number``) — the public number.
    number: Mapped[str] = mapped_column(String(8), nullable=False)
    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(12), nullable=False, server_default=text("'pending'")
    )
    skin_item_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("skin_items.id", ondelete="RESTRICT"), nullable=False
    )
    market_hash_name: Mapped[str] = mapped_column(String(255), nullable=False)
    phase: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("''"))
    #: As ``skin_items.slug`` (the order page links the item).
    slug: Mapped[str] = mapped_column(String(255), nullable=False)
    #: The Waxpeer offer the buyer chose, after any checkout substitution (R4).
    listing_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    #: Waxpeer units we agreed to pay at checkout (1000 = $1); the worker's price cap.
    cost_units: Mapped[int] = mapped_column(Integer, nullable=False)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False)
    price_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False)
    #: What the buyer is billed, whole soʻm.
    price_uzs: Mapped[Decimal] = mapped_column(Numeric(14, 0), nullable=False)
    fx_snapshot_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("fx_snapshots.id", ondelete="RESTRICT"), nullable=False
    )
    #: The buyer's trade link at checkout (PII: never logged).
    trade_link: Mapped[str] = mapped_column(Text, nullable=False)
    #: The customer's ``Idempotency-Key``; unique per user.
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    #: ``wallet``, ``click``, ``payme``, ``uzum`` or ``mock``; ``NULL`` until paid.
    paid_with: Mapped[str | None] = mapped_column(String(16), nullable=True)
    created_at: Mapped[datetime] = _ts()
    updated_at: Mapped[datetime] = _ts()
    #: A ``pending`` order is cancelled after this.
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    paid_at: Mapped[datetime | None] = _at()
    delivered_at: Mapped[datetime | None] = _at()
    cancelled_at: Mapped[datetime | None] = _at()
    #: Stamped by both ``failed`` and ``returned``.
    failed_at: Mapped[datetime | None] = _at()
    refunded_at: Mapped[datetime | None] = _at()
    refunded_to: Mapped[str | None] = mapped_column(String(8), nullable=True)
    #: One of :data:`FAILURE_REASONS`.
    failure_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    claimed_at: Mapped[datetime | None] = _at()
    claimed_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    next_check_at: Mapped[datetime | None] = _at()

    __table_args__ = (
        UniqueConstraint("number", name="uq_orders_number"),
        UniqueConstraint("user_id", "idempotency_key", name="uq_orders_user_id_idempotency_key"),
        # Bare suffixes: the metadata naming convention adds ``ck_orders_``.
        CheckConstraint(f"status IN {_in(ORDER_STATUSES)}", name="status"),
        CheckConstraint(f"refunded_to IN {_in(REFUND_TARGETS)}", name="refunded_to"),
        Index("ix_orders_status_next_check", "status", "next_check_at"),
        Index("ix_orders_user_created", "user_id", text("created_at DESC")),
        # text_pattern_ops: the admin search's prefix LIKE uses it under any collation.
        Index("ix_orders_number", "number", postgresql_ops={"number": "text_pattern_ops"}),
        # The dashboard's windows (M4b R9).
        Index("ix_orders_paid_at", "paid_at", postgresql_where=text("paid_at IS NOT NULL")),
        Index(
            "ix_orders_refunded_at", "refunded_at", postgresql_where=text("refunded_at IS NOT NULL")
        ),
    )


class SkinTrade(Base):
    """The Waxpeer purchase and the Steam trade behind one order (ruling R2)."""

    __tablename__ = "skin_trades"

    order_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("orders.id", ondelete="CASCADE"), primary_key=True
    )
    #: Our id at Waxpeer (= the order id): the buy is looked up by it, never repeated.
    project_id: Mapped[str] = mapped_column(String(64), nullable=False)
    #: Waxpeer's trade id, once the buy answer or a lookup names it.
    waxpeer_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    listing_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    #: The cap we agreed to pay, Waxpeer units.
    paid_units: Mapped[int] = mapped_column(Integer, nullable=False)
    #: What Waxpeer charged, Waxpeer units.
    bought_units: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: Waxpeer's trade status code; ``NULL`` = the buy never reached Waxpeer.
    status: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    #: As received; never parsed.
    escrow_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    #: Steam's trade offer id.
    trade_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    send_until: Mapped[datetime | None] = _at()
    release_date: Mapped[datetime | None] = _at()
    is_released: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    accepted_at: Mapped[datetime | None] = _at()
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Any: Waxpeer's penalties object as received; never PII.
    penalties: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    #: The seller's public name, avatar, level and since (spec §5 ``seller_*``).
    # Any: a JSON object of scalar values.
    seller: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    #: A buy to (re)try on the next tick (HTTP 403 or 429 from Waxpeer, R6).
    buy_pending: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    #: When a buy's answer was lost (network error / 5xx); resolved by lookup (R3).
    buy_unconfirmed_at: Mapped[datetime | None] = _at()
    #: One of :data:`ATTENTION_REASONS`; attention = this set and ``resolved_at`` unset.
    attention_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    audit_verdict: Mapped[str | None] = mapped_column(String(32), nullable=True)
    last_polled_at: Mapped[datetime | None] = _at()
    resolved_at: Mapped[datetime | None] = _at()
    resolved_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    resolved_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = _ts()
    updated_at: Mapped[datetime] = _ts()

    __table_args__ = (
        UniqueConstraint("project_id", name="uq_skin_trades_project_id"),
        CheckConstraint(f"attention_reason IN {_in(ATTENTION_REASONS)}", name="attention_reason"),
        Index("ix_skin_trades_protection", "status", "is_released"),
        Index(
            "ix_skin_trades_attention",
            "attention_reason",
            postgresql_where=text("attention_reason IS NOT NULL AND resolved_at IS NULL"),
        ),
        Index("ix_skin_trades_created_at", "created_at"),
    )


__all__ = [
    "ATTENTION_REASONS",
    "FAILURE_REASONS",
    "IN_FLIGHT",
    "ORDER_STATUSES",
    "REFUND_TARGETS",
    "TERMINAL",
    "Order",
    "SkinTrade",
]
