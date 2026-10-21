"""The risk tables (spec 2026-10-21-payment-risk-limits).

- :class:`KassaReviewLimit` — one row per kassa: above ``max_amount_uzs`` within
  ``window_hours`` a user's payment is held.
- :class:`UserRiskPolicy` — one row per user the admin configured: trusted, blocked, own limit.
- :class:`PaymentHold` — one row per held payment and the decision taken on it.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from csmarket.core.db import Base
from csmarket.core.ids import new_id

# Registers ``payments``, the target of ``payment_holds.payment_id``.
from csmarket.modules.payments import models as _payments_models  # noqa: F401

HOLD_REASONS = ("kassa_limit", "user_limit", "check_failed")
HOLD_DECISIONS = ("released", "returned", "reversed_by_kassa")
HOLD_KINDS = ("topup", "order")
HoldReason = Literal["kassa_limit", "user_limit", "check_failed"]
HoldDecision = Literal["released", "returned", "reversed_by_kassa"]
HoldKind = Literal["topup", "order"]
#: Window bounds in hours, both tables.
MIN_WINDOW_HOURS, MAX_WINDOW_HOURS = 1, 720


def _in(values: tuple[str, ...]) -> str:
    """``('a', 'b')`` as a SQL ``IN`` list."""
    return "(" + ", ".join(f"'{v}'" for v in values) + ")"


_TS = DateTime(timezone=True)
_NOW = text("CURRENT_TIMESTAMP")
_WINDOW = f"window_hours BETWEEN {MIN_WINDOW_HOURS} AND {MAX_WINDOW_HOURS}"


class KassaReviewLimit(Base):
    """A kassa's limit: a user's money through it within the window, above which it is held."""

    __tablename__ = "kassa_review_limits"

    provider: Mapped[str] = mapped_column(String(16), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    max_amount_uzs: Mapped[Decimal] = mapped_column(Numeric(14, 0), nullable=False)
    window_hours: Mapped[int] = mapped_column(Integer, nullable=False, server_default="24")
    updated_by: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id"), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=_NOW)

    __table_args__ = (
        CheckConstraint("max_amount_uzs >= 1", name="max_positive"),
        CheckConstraint(_WINDOW, name="window"),
    )


class UserRiskPolicy(Base):
    """What the admin set on one user; no row = no policy."""

    __tablename__ = "user_risk_policies"

    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    trusted: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    kassa_blocked: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    #: The user's own limit over every kassa; ``NULL`` = none.
    max_amount_uzs: Mapped[Decimal | None] = mapped_column(Numeric(14, 0), nullable=True)
    window_hours: Mapped[int] = mapped_column(Integer, nullable=False, server_default="24")
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_by: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id"), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=_NOW)

    __table_args__ = (
        CheckConstraint("max_amount_uzs IS NULL OR max_amount_uzs >= 1", name="max_positive"),
        CheckConstraint(_WINDOW, name="window"),
    )


class PaymentHold(Base):
    """A kassa payment the rule held, and the decision taken on it (``NULL`` = open)."""

    __tablename__ = "payment_holds"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_id)
    payment_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("payments.id"), nullable=False, unique=True
    )
    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(8), nullable=False)
    provider: Mapped[str] = mapped_column(String(16), nullable=False)
    amount_uzs: Mapped[Decimal] = mapped_column(Numeric(14, 0), nullable=False)
    reason: Mapped[str] = mapped_column(String(16), nullable=False)
    #: The window sum including this payment, and the limit it broke (``NULL`` on check_failed).
    window_sum_uzs: Mapped[Decimal | None] = mapped_column(Numeric(14, 0), nullable=True)
    limit_uzs: Mapped[Decimal | None] = mapped_column(Numeric(14, 0), nullable=True)
    created_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=_NOW)
    decision: Mapped[str | None] = mapped_column(String(20), nullable=True)
    decided_by: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id"), nullable=True
    )
    decided_at: Mapped[datetime | None] = mapped_column(_TS, nullable=True)

    __table_args__ = (
        CheckConstraint(f"kind IN {_in(HOLD_KINDS)}", name="kind"),
        CheckConstraint(f"reason IN {_in(HOLD_REASONS)}", name="reason"),
        CheckConstraint(f"decision IS NULL OR decision IN {_in(HOLD_DECISIONS)}", name="decision"),
        CheckConstraint("(decision IS NULL) = (decided_at IS NULL)", name="decided_pair"),
        Index(
            "ix_payment_holds_open",
            text("created_at DESC"),
            postgresql_where=text("decision IS NULL"),
        ),
        Index(
            "ix_payment_holds_decided",
            text("decided_at DESC"),
            postgresql_where=text("decision IS NOT NULL"),
        ),
        Index("ix_payment_holds_user", "user_id"),
    )
