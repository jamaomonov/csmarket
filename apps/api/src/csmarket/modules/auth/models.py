"""``refresh_tokens`` — one row per issued refresh token (spec §5).

Only the SHA-256 of the opaque token is stored. A row is a *session*: its id is the
``sid`` claim in every access token minted from it, which is what lets revoking the row
kill those access tokens at once (Redis ``auth:revoked_sid:{sid}``).

``revoked_reason`` says why a row was revoked, which decides what presenting it again
means (``service.refresh_session``): only a ``rotated`` token coming back is theft.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CHAR, CheckConstraint, DateTime, ForeignKey, String, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from csmarket.core.db import Base


class RefreshToken(Base):
    """A rotating refresh token's server-side record."""

    __tablename__ = "refresh_tokens"
    __table_args__ = (
        CheckConstraint(
            "revoked_reason IN ('rotated', 'logout', 'admin', 'reuse')", name="revoked_reason"
        ),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    #: ``rotated`` | ``logout`` | ``admin`` (ban) | ``reuse`` (the trip-wire's burn-down);
    #: NULL on rows revoked before 0011, read as ``rotated``.
    revoked_reason: Mapped[str | None] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
