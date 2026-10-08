"""SQLAlchemy ORM for the ``public_api`` module: the customer's API key.

One live key per user (a partial unique index); a reissue revokes the old row. Only the
``sha256`` of the token is stored — the token itself is shown once and never logged.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, text
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column

from csmarket.core.db import Base
from csmarket.core.ids import new_id

#: ``api_keys.pricing_profile``: ``retail`` = storefront rules, ``cost`` = the offer's cost.
PRICING_PROFILES = ("retail", "cost")


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


__all__ = ["PRICING_PROFILES", "ApiKey"]
