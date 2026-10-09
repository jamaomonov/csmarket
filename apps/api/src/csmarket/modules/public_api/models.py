"""SQLAlchemy ORM for the ``public_api`` module: the customer's API key.

One live key per user (a partial unique index); a reissue revokes the old row. Only the
``sha256`` of the token is stored — the token itself is shown once and never logged.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from csmarket.core.db import Base
from csmarket.core.ids import new_id

#: ``api_keys.pricing_profile``: ``retail`` = storefront rules, ``cost`` = the offer's cost.
PRICING_PROFILES = ("retail", "cost")
#: The events a partner webhook is told about, one delivery per ``(order, event)``.
WEBHOOK_EVENTS = ("order.paid", "order.trade_sent", "order.delivered", "order.refunded")
#: ``api_webhook_deliveries.status``.
DELIVERY_STATUSES = ("pending", "sent", "failed")


class ApiKey(Base):
    """A customer's API key (hash only)."""

    __tablename__ = "api_keys"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    #: Hex ``sha256`` of the token.
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    pricing_profile: Mapped[str] = mapped_column(
        String(8), nullable=False, server_default=text("'retail'"), default="retail"
    )
    #: Client IPs allowed to use the key (IPv4 / IPv6 text); empty = any.
    ip_allowlist: Mapped[list[str]] = mapped_column(
        ARRAY(String(43)), nullable=False, server_default=text("'{}'"), default=list
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        # Bare suffix: the metadata naming convention adds ``ck_api_keys_``.
        CheckConstraint(
            "pricing_profile IN (" + ", ".join(f"'{p}'" for p in PRICING_PROFILES) + ")",
            name="pricing_profile",
        ),
        Index(
            "uq_api_keys_live_user",
            "user_id",
            unique=True,
            postgresql_where=text("revoked_at IS NULL"),
        ),
    )


class ApiWebhook(Base):
    """A partner's webhook URL, one per user (it follows the user across key reissues)."""

    __tablename__ = "api_webhooks"

    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    url: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )


class ApiWebhookDelivery(Base):
    """One event to deliver for one order (unique per ``(order, event)``)."""

    __tablename__ = "api_webhook_deliveries"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    order_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("orders.id", ondelete="RESTRICT"), nullable=False
    )
    event: Mapped[str] = mapped_column(String(24), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)  # JSON body
    status: Mapped[str] = mapped_column(
        String(8), nullable=False, server_default=text("'pending'"), default="pending"
    )
    attempts: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default=text("0"), default=0
    )
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_status_code: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )

    __table_args__ = (
        CheckConstraint(
            "event IN (" + ", ".join(f"'{e}'" for e in WEBHOOK_EVENTS) + ")", name="event"
        ),
        CheckConstraint(
            "status IN (" + ", ".join(f"'{s}'" for s in DELIVERY_STATUSES) + ")", name="status"
        ),
        UniqueConstraint("order_id", "event", name="uq_api_webhook_deliveries_order_id_event"),
        Index(
            "ix_api_webhook_deliveries_pending",
            "status",
            "next_attempt_at",
            postgresql_where=text("status = 'pending'"),
        ),
    )


__all__ = [
    "DELIVERY_STATUSES",
    "PRICING_PROFILES",
    "WEBHOOK_EVENTS",
    "ApiKey",
    "ApiWebhook",
    "ApiWebhookDelivery",
]
