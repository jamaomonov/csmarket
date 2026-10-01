"""The ``users`` table — one row per Steam account (spec §5).

``steam_id`` is the identity (steamid64, stored as text: it is an identifier, never
arithmetic, and JSON clients lose precision on 64-bit ints). Everything else is profile
or state the account page edits.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import ARRAY, CheckConstraint, DateTime, String, Text, text
from sqlalchemy.dialects.postgresql import CITEXT, UUID
from sqlalchemy.orm import Mapped, mapped_column

from csmarket.core.db import Base

LOCALES = ("ru", "uz", "en")
TRADE_LINK_VERDICTS = ("ok", "warn", "bad")
TRADE_LINK_REASONS = ("invalid", "private", "trade_ban", "hold", "unavailable")


class User(Base):
    """A signed-in customer (or admin — same table, ``roles`` tells them apart)."""

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    steam_id: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    email: Mapped[str | None] = mapped_column(CITEXT(), nullable=True)
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    locale: Mapped[str] = mapped_column(String(2), nullable=False, server_default="ru")
    trade_link: Mapped[str | None] = mapped_column(Text, nullable=True)
    trade_link_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    trade_link_verdict: Mapped[str | None] = mapped_column(String(8), nullable=True)
    trade_link_reason: Mapped[str | None] = mapped_column(String(16), nullable=True)
    roles: Mapped[list[str]] = mapped_column(
        ARRAY(String(32)), nullable=False, server_default=text("'{}'::varchar[]")
    )
    banned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ban_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint("locale IN ('ru', 'uz', 'en')", name="locale"),
        CheckConstraint(
            "trade_link_verdict IS NULL OR trade_link_verdict IN ('ok', 'warn', 'bad')",
            name="trade_link_verdict",
        ),
        CheckConstraint(
            "trade_link_reason IS NULL OR trade_link_reason IN "
            "('invalid', 'private', 'trade_ban', 'hold', 'unavailable')",
            name="trade_link_reason",
        ),
    )
