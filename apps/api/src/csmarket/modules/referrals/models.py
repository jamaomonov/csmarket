"""SQLAlchemy ORM for ``referrals`` (spec ``2026-10-27-referrals-design.md``, ADR-0026).

- :class:`ReferralPartner` — an account the admin made a partner: its link code, percent of
  each purchase and attribution term (``NULL`` = forever).
- :class:`ReferralAttribution` — an account tied to the partner whose link it came by, written
  once, at the account's first sign-in.
- :class:`ReferralReward` — one per delivered order of an attributed buyer: ``held`` for
  :data:`HOLD`, then ``credited`` to the partner's balance or ``cancelled``.
- :class:`ReferralVisitDay` — link visits per partner per day (deduped per visitor in Redis).

No IP, name or Steam ID is stored here; a reward names the order only for the admin.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy import text as sql_text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from csmarket.core.db import Base

REWARD_STATUSES = ("held", "credited", "cancelled")
CANCEL_REASONS = ("rolled_back",)
#: Steam lets a trade be reversed for 7 days (trade protection); a reward waits one more.
HOLD = timedelta(days=8)
PERCENT_MIN = Decimal("0.1")
PERCENT_MAX = Decimal("20")
TERM_MAX = 120
DEFAULT_TERM = 6
CODE_PATTERN = r"^[a-z0-9-]{3,32}$"
#: The link a visitor came by, remembered on the API host until the sign-in reads it.
REF_COOKIE = "csm_ref"
REF_MAX_AGE = 30 * 24 * 3600


def _in(values: tuple[str, ...]) -> str:
    """``('a', 'b')`` as a SQL ``IN`` list."""
    return "(" + ", ".join(f"'{v}'" for v in values) + ")"


def _ts() -> Mapped[datetime]:
    """A ``NOT NULL`` timestamp the database fills in."""
    return mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sql_text("CURRENT_TIMESTAMP")
    )


def _user_fk(*, ondelete: str) -> ForeignKey:
    return ForeignKey("users.id", ondelete=ondelete)


class ReferralPartner(Base):
    """An account that earns from the accounts its link brings."""

    __tablename__ = "referral_partners"

    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), _user_fk(ondelete="CASCADE"), primary_key=True
    )
    code: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    percent: Mapped[Decimal] = mapped_column(Numeric(4, 1), nullable=False)
    #: Months a referred account earns for the partner; ``None`` = forever.
    term_months: Mapped[int | None] = mapped_column(Integer, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=sql_text("true"))
    #: When the partner was last switched on: deliveries before it never earn, so a partner
    #: switched off and back on is not paid for the days it was off.
    active_since: Mapped[datetime] = _ts()
    #: The admin's own note; never shown to the partner, never in an audit payload.
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = _ts()
    updated_at: Mapped[datetime] = _ts()

    __table_args__ = (
        CheckConstraint(f"percent >= {PERCENT_MIN} AND percent <= {PERCENT_MAX}", name="percent"),
        CheckConstraint(
            f"term_months IS NULL OR (term_months >= 1 AND term_months <= {TERM_MAX})",
            name="term_months",
        ),
        CheckConstraint(f"code ~ '{CODE_PATTERN}'", name="code"),
    )


class ReferralAttribution(Base):
    """The partner an account came by; one per account, never moved."""

    __tablename__ = "referral_attributions"

    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), _user_fk(ondelete="CASCADE"), primary_key=True
    )
    partner_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("referral_partners.user_id", ondelete="RESTRICT"),
        nullable=False,
    )
    attributed_at: Mapped[datetime] = _ts()

    __table_args__ = (Index("ix_referral_attributions_partner", "partner_id"),)


class ReferralReward(Base):
    """A partner's share of one delivered order."""

    __tablename__ = "referral_rewards"

    order_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("orders.id", ondelete="RESTRICT"), primary_key=True
    )
    partner_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("referral_partners.user_id", ondelete="RESTRICT"),
        nullable=False,
    )
    referred_user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), _user_fk(ondelete="RESTRICT"), nullable=False
    )
    #: The order's ``price_uzs``.
    base_uzs: Mapped[Decimal] = mapped_column(Numeric(14, 0), nullable=False)
    #: The partner's percent when the reward was written.
    percent: Mapped[Decimal] = mapped_column(Numeric(4, 1), nullable=False)
    amount_uzs: Mapped[Decimal] = mapped_column(Numeric(14, 0), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    delivered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    credited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    #: When ``settle`` last left it waiting; the never-checked go first, so rewards that can
    #: only wait (a banned partner, a frozen wallet) never hold up the rest.
    checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _ts()

    __table_args__ = (
        CheckConstraint("amount_uzs > 0", name="amount_positive"),
        CheckConstraint(f"status IN {_in(REWARD_STATUSES)}", name="status"),
        CheckConstraint(
            f"cancelled_reason IS NULL OR cancelled_reason IN {_in(CANCEL_REASONS)}",
            name="cancelled_reason",
        ),
        Index(
            "ix_referral_rewards_due",
            "available_at",
            postgresql_where=sql_text("status = 'held'"),
        ),
        Index("ix_referral_rewards_partner", "partner_id", "delivered_at"),
    )


class ReferralVisitDay(Base):
    """How many visitors came by a partner's link on one UTC day."""

    __tablename__ = "referral_visit_days"

    partner_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("referral_partners.user_id", ondelete="CASCADE"),
        primary_key=True,
    )
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    visits: Mapped[int] = mapped_column(Integer, nullable=False, server_default=sql_text("0"))

    __table_args__ = (CheckConstraint("visits >= 0", name="visits"),)


__all__ = [
    "CANCEL_REASONS",
    "CODE_PATTERN",
    "DEFAULT_TERM",
    "HOLD",
    "PERCENT_MAX",
    "PERCENT_MIN",
    "REF_COOKIE",
    "REF_MAX_AGE",
    "REWARD_STATUSES",
    "TERM_MAX",
    "ReferralAttribution",
    "ReferralPartner",
    "ReferralReward",
    "ReferralVisitDay",
]
