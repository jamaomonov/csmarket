"""SQLAlchemy ORM for ``desk`` (spec ``2026-10-29-desk-design.md``, ADR-0027).

- :class:`DeskDeal` — one purchase from one trader: who, the price paid and how.
- :class:`DeskItem` — a skin of a deal, bound for Skinslink or the owner's own Steam stock,
  with its share of the price (``cost_usd``) and how it ended.
- :class:`DeskDeposit` — a Skinslink deposit sent for a deal; ``merchant_tx_id`` is
  ``desk-{id}`` (:data:`DESK_TX_PREFIX`), so the shop's sales never read it.
- :class:`DeskEntry` — the profit ledger: one signed USD row per item resolved or reverted; a
  period's profit is the sum of its rows.
- :class:`DeskWithdrawal` — what the owner took out of our Skinslink balance for himself.

Nothing here is read by the shop's sales, wallet, analytics or alerts.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy import text as sql_text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from csmarket.core.db import Base

DEAL_STATUSES = ("agreed", "paid", "received", "closed", "cancelled", "reverted")
CURRENCIES = ("UZS", "USD")
METHODS = ("direct", "guarantor")
DESTINATIONS = ("skinslink", "stock")
ITEM_STATES = ("open", "sent", "credited", "sold", "written_off", "reverted")
#: An item in one of these is resolved: its profit is known.
RESOLVED = frozenset({"credited", "sold", "written_off", "reverted"})
ENTRY_KINDS = ("credit", "sale", "revert", "write_off")
#: Skinslink deposit statuses that end it (no more polling once settled).
DEPOSIT_DEAD = ("failed", "canceled", "reverted")
DESK_TX_PREFIX = "desk-"
_USD = Numeric(18, 6)


def _in(values: tuple[str, ...]) -> str:
    """``('a', 'b')`` as a SQL ``IN`` list."""
    return "(" + ", ".join(f"'{v}'" for v in values) + ")"


def _ts() -> Mapped[datetime]:
    """A ``NOT NULL`` timestamp the database fills in."""
    return mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sql_text("CURRENT_TIMESTAMP")
    )


def _at() -> Mapped[datetime | None]:
    return mapped_column(DateTime(timezone=True), nullable=True)


def _id() -> Mapped[str]:
    return mapped_column(UUID(as_uuid=False), primary_key=True)


def _fk(table: str, *, nullable: bool = False) -> Mapped[str]:
    return mapped_column(
        UUID(as_uuid=False), ForeignKey(f"{table}.id", ondelete="RESTRICT"), nullable=nullable
    )


class DeskDeal(Base):
    """One purchase from one trader."""

    __tablename__ = "desk_deals"

    id: Mapped[str] = _id()
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    #: The trader's name or handle as the owner writes it — never logged.
    trader: Mapped[str] = mapped_column(String(120), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Only when a deposit is sent; PII, never logged.
    trade_link: Mapped[str | None] = mapped_column(Text, nullable=True)
    paid_amount: Mapped[Decimal | None] = mapped_column(_USD, nullable=True)
    paid_currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    #: Soʻm per dollar for a ``UZS`` price.
    rate: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    paid_usd: Mapped[Decimal | None] = mapped_column(_USD, nullable=True)
    method: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=sql_text("'direct'")
    )
    paid_at: Mapped[datetime | None] = _at()
    guarantor_released_at: Mapped[datetime | None] = _at()
    created_at: Mapped[datetime] = _ts()
    updated_at: Mapped[datetime] = _ts()

    __table_args__ = (
        CheckConstraint(f"status IN {_in(DEAL_STATUSES)}", name="status"),
        CheckConstraint(f"method IN {_in(METHODS)}", name="method"),
        CheckConstraint(
            f"paid_currency IS NULL OR paid_currency IN {_in(CURRENCIES)}", name="currency"
        ),
        CheckConstraint(
            "paid_amount IS NULL OR (paid_amount > 0 AND paid_currency IS NOT NULL"
            " AND paid_usd IS NOT NULL AND (paid_currency = 'USD' OR rate > 0))",
            name="price",
        ),
        Index("ix_desk_deals_created", "created_at"),
    )


class DeskDeposit(Base):
    """A Skinslink deposit sent for a deal (``merchant_tx_id`` = ``desk-{id}``)."""

    __tablename__ = "desk_deposits"

    id: Mapped[str] = _id()
    deal_id: Mapped[str] = _fk("desk_deals")
    skinslink_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: ``creating`` until Skinslink answers, then Skinslink's own status.
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    amount_usd: Mapped[Decimal | None] = mapped_column(_USD, nullable=True)
    trade_offer_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    offer_expiry_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    hold_end_date: Mapped[str | None] = mapped_column(String(40), nullable=True)
    fail_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    next_check_at: Mapped[datetime] = _ts()
    #: When the trader accepted (first seen in ``hold`` or ``completed``).
    accepted_at: Mapped[datetime | None] = _at()
    credited_at: Mapped[datetime | None] = _at()
    reverted_at: Mapped[datetime | None] = _at()
    created_at: Mapped[datetime] = _ts()

    __table_args__ = (
        Index("ix_desk_deposits_deal", "deal_id"),
        Index(
            "ix_desk_deposits_due",
            "next_check_at",
            postgresql_where=sql_text(f"status NOT IN {_in(DEPOSIT_DEAD)}"),
        ),
    )

    @property
    def merchant_tx_id(self) -> str:
        """Our id at Skinslink."""
        return f"{DESK_TX_PREFIX}{self.id}"


class DeskItem(Base):
    """A skin of a deal."""

    __tablename__ = "desk_items"

    id: Mapped[str] = _id()
    deal_id: Mapped[str] = _fk("desk_deals")
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    asset_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    image_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Skinslink's price when the deal was priced; the weight of the price split.
    skinslink_usd: Mapped[Decimal | None] = mapped_column(_USD, nullable=True)
    destination: Mapped[str] = mapped_column(String(16), nullable=False)
    #: The item's share of the deal's price; ``None`` until the deal has a price.
    cost_usd: Mapped[Decimal | None] = mapped_column(_USD, nullable=True)
    state: Mapped[str] = mapped_column(String(16), nullable=False, server_default="open")
    deposit_id: Mapped[str | None] = _fk("desk_deposits", nullable=True)
    sold_where: Mapped[str | None] = mapped_column(String(120), nullable=True)
    sold_amount: Mapped[Decimal | None] = mapped_column(_USD, nullable=True)
    sold_currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    sold_rate: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    sold_usd: Mapped[Decimal | None] = mapped_column(_USD, nullable=True)
    resolved_at: Mapped[datetime | None] = _at()
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint(f"destination IN {_in(DESTINATIONS)}", name="destination"),
        CheckConstraint(f"state IN {_in(ITEM_STATES)}", name="state"),
        Index("ix_desk_items_deal", "deal_id"),
        Index(
            "ix_desk_items_stock",
            "deal_id",
            postgresql_where=sql_text("destination = 'stock' AND state = 'open'"),
        ),
    )


class DeskEntry(Base):
    """One signed USD row of the profit ledger."""

    __tablename__ = "desk_entries"

    id: Mapped[str] = _id()
    deal_id: Mapped[str] = _fk("desk_deals")
    item_id: Mapped[str] = _fk("desk_items")
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    profit_usd: Mapped[Decimal] = mapped_column(_USD, nullable=False)
    #: Skinslink money this row moved (``credit`` +, ``revert`` −; 0 otherwise).
    revenue_usd: Mapped[Decimal] = mapped_column(_USD, nullable=False, server_default=sql_text("0"))
    at: Mapped[datetime] = _ts()

    __table_args__ = (
        CheckConstraint(f"kind IN {_in(ENTRY_KINDS)}", name="kind"),
        Index("uq_desk_entries_item_kind", "item_id", "kind", unique=True),
        Index("ix_desk_entries_at", "at"),
    )


class DeskWithdrawal(Base):
    """Money the owner took out of our Skinslink balance for himself."""

    __tablename__ = "desk_withdrawals"

    id: Mapped[str] = _id()
    amount_usd: Mapped[Decimal] = mapped_column(_USD, nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    at: Mapped[datetime] = _ts()

    __table_args__ = (CheckConstraint("amount_usd > 0", name="amount"),)


__all__ = [
    "CURRENCIES",
    "DEAL_STATUSES",
    "DESK_TX_PREFIX",
    "DESTINATIONS",
    "ENTRY_KINDS",
    "ITEM_STATES",
    "METHODS",
    "RESOLVED",
    "DeskDeal",
    "DeskDeposit",
    "DeskEntry",
    "DeskItem",
    "DeskWithdrawal",
]
