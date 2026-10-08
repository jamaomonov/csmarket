"""SQLAlchemy ORM for the ``sales`` module (spec 2026-10-08 §4).

- :class:`Sale` — one Skinslink deposit; its ``id`` is the ``merchant_tx_id``. Its payout is
  fixed when it is created; ``amount_usd`` is what Skinslink says it credits us.
- :class:`SaleItem` — the items of a sale, at the prices the user saw.
- :class:`PayoutCard` — a saved card, encrypted under :data:`CARD_PURPOSE`; only ``last4`` is
  in the clear. Deleted softly: a paid request keeps pointing at its card.
- :class:`PayoutRequest` — a card payout an admin pays by hand; at most one per sale.
- :class:`SaleSettingsRow` — row 1, the admin's document (``rules.SaleSettings``).
- :class:`SaleCheck` — «ask Skinslink about sale N»: queued by the webhook, drained by the
  worker's ``sales`` queue.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
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
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from csmarket.core.db import Base
from csmarket.core.ids import new_id

#: The LISTEN channel of the worker's ``sales`` queue.
SALES_CHANNEL = "sales"
#: The ``core.crypto`` purpose label of a card number. A new cipher means a new label.
CARD_PURPOSE = "csmarket:payout-card:v1"

SALE_STATUSES = ("creating", "offered", "hold", "credited", "payout", "closed", "reverted")
#: Statuses Skinslink may still move; everything else is settled.
OPEN_STATUSES = ("creating", "offered", "hold")
PAYOUT_TO = ("balance", "card")
CARD_TYPES = ("uzcard", "humo", "uzum_visa")
REQUEST_STATUSES = ("waiting_hold", "to_pay", "paid", "rejected", "canceled")
#: ``rolled_back``: reverted after the money left; ``late_deposit``: a closed sale Skinslink
#: reports alive. Both wait for an admin (``docs/runbooks/sales.md``).
ATTENTION_REASONS = ("rolled_back", "late_deposit")


def _in(values: tuple[str, ...]) -> str:
    """``('a', 'b')`` as a SQL ``IN`` list."""
    return "(" + ", ".join(f"'{v}'" for v in values) + ")"


def _ts() -> Mapped[datetime]:
    """A ``NOT NULL`` timestamp the database fills in."""
    return mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )


def _at() -> Mapped[datetime | None]:
    """A nullable timestamp."""
    return mapped_column(DateTime(timezone=True), nullable=True)


class PayoutCard(Base):
    """A user's saved payout card."""

    __tablename__ = "payout_cards"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    type: Mapped[str] = mapped_column(String(16), nullable=False)
    #: The 16 digits, encrypted (``core.crypto``, :data:`CARD_PURPOSE`). PII.
    number_enc: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    number_nonce: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    last4: Mapped[str] = mapped_column(String(4), nullable=False)
    created_at: Mapped[datetime] = _ts()
    deleted_at: Mapped[datetime | None] = _at()

    __table_args__ = (
        CheckConstraint(f"type IN {_in(CARD_TYPES)}", name="type"),
        Index("ix_payout_cards_user_live", "user_id", postgresql_where=text("deleted_at IS NULL")),
    )


class Sale(Base):
    """One sale: the user's items deposited at Skinslink, our payout fixed at creation."""

    __tablename__ = "sales"

    #: Also the Skinslink ``merchant_tx_id``.
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    #: ``S`` + 7 Crockford chars (``core.numbers.sale_number``).
    number: Mapped[str] = mapped_column(String(8), nullable=False)
    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'creating'")
    )
    payout_to: Mapped[str] = mapped_column(String(8), nullable=False)
    payout_card_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("payout_cards.id", ondelete="RESTRICT"), nullable=True
    )
    #: The sum of the items' Skinslink prices when the sale was created, USD.
    quoted_usd: Mapped[Decimal] = mapped_column(Numeric(14, 6), nullable=False)
    #: What Skinslink says it credits us (Create Deposit's ``amount``), USD.
    amount_usd: Mapped[Decimal | None] = mapped_column(Numeric(14, 6), nullable=True)
    #: The sum of the items' soʻm prices, before the bonus or the card fee.
    items_uzs: Mapped[Decimal] = mapped_column(Numeric(14, 0), nullable=False)
    #: What the user gets, fixed at creation.
    payout_uzs: Mapped[Decimal] = mapped_column(Numeric(14, 0), nullable=False)
    #: The sale rate: the CBU rate less ``rate_cut_pct``.
    rate: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    margin_usd: Mapped[Decimal] = mapped_column(Numeric(14, 6), nullable=False)
    #: Skinslink's deposit id (``trade_id`` in its webhook).
    trade_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    trade_offer_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    bot_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    offer_expiry_at: Mapped[datetime | None] = _at()
    hold_end_at: Mapped[datetime | None] = _at()
    fail_reason: Mapped[str | None] = mapped_column(String(48), nullable=True)
    credited_at: Mapped[datetime | None] = _at()
    attention_reason: Mapped[str | None] = mapped_column(String(16), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    last_polled_at: Mapped[datetime | None] = _at()
    created_at: Mapped[datetime] = _ts()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
        onupdate=text("CURRENT_TIMESTAMP"),
    )

    __table_args__ = (
        UniqueConstraint("number", name="uq_sales_number"),
        UniqueConstraint("user_id", "idempotency_key", name="uq_sales_user_id_idempotency_key"),
        CheckConstraint(f"status IN {_in(SALE_STATUSES)}", name="status"),
        CheckConstraint(f"payout_to IN {_in(PAYOUT_TO)}", name="payout_to"),
        CheckConstraint("(payout_to = 'card') = (payout_card_id IS NOT NULL)", name="payout_card"),
        CheckConstraint(
            f"attention_reason IS NULL OR attention_reason IN {_in(ATTENTION_REASONS)}",
            name="attention_reason",
        ),
        Index("ix_sales_user_created", "user_id", text("created_at DESC")),
        Index(
            "ix_sales_open",
            "status",
            "last_polled_at",
            postgresql_where=text("status IN ('creating', 'offered', 'hold')"),
        ),
    )


class SaleItem(Base):
    """One item of a sale, at the prices the user saw."""

    __tablename__ = "sale_items"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_id)
    sale_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("sales.id", ondelete="CASCADE"), nullable=False
    )
    #: Steam's asset id in the user's inventory.
    asset_id: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    image_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Skinslink's price, USD.
    price_usd: Mapped[Decimal] = mapped_column(Numeric(14, 6), nullable=False)
    #: Our price, soʻm.
    price_uzs: Mapped[Decimal] = mapped_column(Numeric(14, 0), nullable=False)

    __table_args__ = (
        UniqueConstraint("sale_id", "asset_id", name="uq_sale_items_sale_id_asset_id"),
    )


class PayoutRequest(Base):
    """A card payout: opened at ``hold``, payable at ``completed``, paid or rejected by hand."""

    __tablename__ = "payout_requests"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_id)
    sale_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("sales.id", ondelete="RESTRICT"), nullable=False
    )
    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    card_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("payout_cards.id", ondelete="RESTRICT"), nullable=False
    )
    #: What goes to the card (the sale's ``payout_uzs``).
    amount_uzs: Mapped[Decimal] = mapped_column(Numeric(14, 0), nullable=False)
    #: The card fee kept (``items_uzs − payout_uzs``); a rejection credits both.
    fee_uzs: Mapped[Decimal] = mapped_column(Numeric(14, 0), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    #: Since when it is payable (``completed`` seen).
    to_pay_at: Mapped[datetime | None] = _at()
    #: The admin who paid or rejected it.
    paid_by: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    paid_at: Mapped[datetime | None] = _at()
    rejected_at: Mapped[datetime | None] = _at()
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    reject_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = _ts()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
        onupdate=text("CURRENT_TIMESTAMP"),
    )

    __table_args__ = (
        UniqueConstraint("sale_id", name="uq_payout_requests_sale_id"),
        CheckConstraint(f"status IN {_in(REQUEST_STATUSES)}", name="status"),
        Index("ix_payout_requests_status_due", "status", "to_pay_at"),
        Index("ix_payout_requests_user_created", "user_id", text("created_at DESC")),
    )


class SaleSettingsRow(Base):
    """Row 1: the sale-settings document (``rules.SaleSettings``) an admin edits."""

    __tablename__ = "sale_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Any: a JSONB document validated by ``rules.SaleSettings`` on every read.
    settings: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    updated_by: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    updated_at: Mapped[datetime] = _ts()

    __table_args__ = (CheckConstraint("id = 1", name="singleton"),)


class SaleCheck(Base):
    """«Ask Skinslink about sale N» — one-shot, drained by the worker."""

    __tablename__ = "sale_checks"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_id)
    sale_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("sales.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = _ts()

    __table_args__ = (Index("ix_sale_checks_created_at", "created_at"),)


__all__ = [
    "ATTENTION_REASONS",
    "CARD_PURPOSE",
    "CARD_TYPES",
    "OPEN_STATUSES",
    "PAYOUT_TO",
    "REQUEST_STATUSES",
    "SALES_CHANNEL",
    "SALE_STATUSES",
    "PayoutCard",
    "PayoutRequest",
    "Sale",
    "SaleCheck",
    "SaleItem",
    "SaleSettingsRow",
]
