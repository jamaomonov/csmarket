"""SQLAlchemy ORM for ``reviews`` (spec ``2026-10-23-reviews-design.md``, ADR-0023).

- :class:`Review` — one per deal (an order or a sale): 1–5 stars, an optional plain text, the
  interface locale at submission. Published = ``rating >= 4 AND NOT hidden``, computed by
  :func:`published`, never stored.
- :class:`ReviewPrompt` — one row per deal the user answered the prompt for: «Не сейчас»
  (``snoozed_until``) or × (``dismissed``). Server-side, so it holds on every device.
- :class:`ReviewSettingsRow` — row 1: ``reviews_public``, the public page's switch.

The review text is the user's own words: never logged, never in an audit payload.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    and_,
)
from sqlalchemy import text as sql_text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql.elements import ColumnElement

from csmarket.core.db import Base
from csmarket.core.ids import new_id

REVIEW_KINDS = ("market", "sale")
REVIEW_LOCALES = ("ru", "uz", "en")
#: Owner ruling 2: 4–5 stars is good (published once the page is on), 1–3 bad (never).
GOOD_FROM = 4
TEXT_MAX = 1000
#: How long after the deal succeeded it may be reviewed, and its review edited.
REVIEW_WINDOW = timedelta(days=14)
#: «Не сейчас» hides the prompt for this long.
SNOOZE = timedelta(days=3)

_ONE_DEAL = "(order_id IS NULL) <> (sale_id IS NULL)"
_KIND_DEAL = "(kind = 'market') = (order_id IS NOT NULL)"


def _in(values: tuple[str, ...]) -> str:
    """``('a', 'b')`` as a SQL ``IN`` list."""
    return "(" + ", ".join(f"'{v}'" for v in values) + ")"


def _ts() -> Mapped[datetime]:
    """A ``NOT NULL`` timestamp the database fills in."""
    return mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sql_text("CURRENT_TIMESTAMP")
    )


def _deal_fk(table: str) -> Mapped[str | None]:
    """A nullable FK to ``orders`` or ``sales``: a deal is never deleted under its review."""
    return mapped_column(
        UUID(as_uuid=False), ForeignKey(f"{table}.id", ondelete="RESTRICT"), nullable=True
    )


class Review(Base):
    """One user's stars (and words) about one deal."""

    __tablename__ = "reviews"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_id)
    #: One of :data:`REVIEW_KINDS`.
    kind: Mapped[str] = mapped_column(String(8), nullable=False)
    order_id: Mapped[str | None] = _deal_fk("orders")
    sale_id: Mapped[str | None] = _deal_fk("sales")
    #: The author: the deal's owner.
    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    rating: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    #: As typed, trimmed; ``NULL`` when blank. Plain text: rendered as text, never logged.
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: The interface locale at submission (owner ruling 6).
    locale: Mapped[str] = mapped_column(String(2), nullable=False)
    #: An admin hid it from the public page.
    hidden: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=sql_text("false"), default=False
    )
    #: A bad review handled by an admin («Разобрано»): when, who, what they did.
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_by: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    resolved_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = _ts()
    updated_at: Mapped[datetime] = _ts()

    __table_args__ = (
        UniqueConstraint("order_id", name="uq_reviews_order_id"),
        UniqueConstraint("sale_id", name="uq_reviews_sale_id"),
        # Bare suffixes: the metadata naming convention adds ``ck_reviews_``.
        CheckConstraint(f"kind IN {_in(REVIEW_KINDS)}", name="kind"),
        CheckConstraint(f"locale IN {_in(REVIEW_LOCALES)}", name="locale"),
        CheckConstraint("rating BETWEEN 1 AND 5", name="rating"),
        CheckConstraint(
            f"text IS NULL OR char_length(text) BETWEEN 1 AND {TEXT_MAX}", name="text_len"
        ),
        CheckConstraint(_ONE_DEAL, name="one_deal"),
        CheckConstraint(_KIND_DEAL, name="kind_deal"),
        Index("ix_reviews_created_at", "created_at"),
        Index("ix_reviews_user_id", "user_id"),
        Index(
            "ix_reviews_bad_open",
            "created_at",
            postgresql_where=sql_text("rating <= 3 AND resolved_at IS NULL"),
        ),
        Index(
            "ix_reviews_published",
            "created_at",
            postgresql_where=sql_text("rating >= 4 AND NOT hidden"),
        ),
    )


class ReviewPrompt(Base):
    """The user's answer to the prompt for one deal: snoozed until, or dismissed for good."""

    __tablename__ = "review_prompts"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(8), nullable=False)
    order_id: Mapped[str | None] = _deal_fk("orders")
    sale_id: Mapped[str | None] = _deal_fk("sales")
    #: «Не сейчас»: no prompt before this.
    snoozed_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: ×: no prompt for this deal again.
    dismissed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=sql_text("false"), default=False
    )
    updated_at: Mapped[datetime] = _ts()

    __table_args__ = (
        UniqueConstraint("order_id", name="uq_review_prompts_order_id"),
        UniqueConstraint("sale_id", name="uq_review_prompts_sale_id"),
        CheckConstraint(f"kind IN {_in(REVIEW_KINDS)}", name="kind"),
        CheckConstraint(_ONE_DEAL, name="one_deal"),
        CheckConstraint(_KIND_DEAL, name="kind_deal"),
        Index("ix_review_prompts_user_id", "user_id"),
    )


class ReviewSettingsRow(Base):
    """Row 1: whether the public page shows the published reviews (default off)."""

    __tablename__ = "review_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    reviews_public: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=sql_text("false"), default=False
    )
    updated_by: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    updated_at: Mapped[datetime] = _ts()

    __table_args__ = (CheckConstraint("id = 1", name="singleton"),)


def published() -> ColumnElement[bool]:
    """Published = good and not hidden (spec «Data»): the one definition every query uses."""
    return and_(Review.rating >= GOOD_FROM, Review.hidden.is_(False))


def bad() -> ColumnElement[bool]:
    """1–3 stars."""
    return Review.rating < GOOD_FROM


__all__ = [
    "GOOD_FROM",
    "REVIEW_KINDS",
    "REVIEW_LOCALES",
    "REVIEW_WINDOW",
    "SNOOZE",
    "TEXT_MAX",
    "Review",
    "ReviewPrompt",
    "ReviewSettingsRow",
    "bad",
    "published",
]
