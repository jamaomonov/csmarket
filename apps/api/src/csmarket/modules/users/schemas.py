"""Wire shapes for ``/me``."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from csmarket.modules.users.models import User


class MeOut(BaseModel):
    """The signed-in account as its owner sees it (the trade link is theirs to see)."""

    id: str
    steam_id: str
    display_name: str | None
    avatar_url: str | None
    email: str | None
    email_verified: bool
    locale: Literal["ru", "uz", "en"]
    trade_link: str | None
    trade_link_verdict: Literal["ok", "warn", "bad"] | None
    trade_link_reason: Literal["invalid", "private", "trade_ban", "hold", "unavailable"] | None
    trade_link_checked_at: datetime | None
    roles: list[str]
    created_at: datetime

    @classmethod
    def of(cls, user: User) -> MeOut:
        """Build from the ORM row."""
        return cls(
            id=user.id,
            steam_id=user.steam_id,
            display_name=user.display_name,
            avatar_url=user.avatar_url,
            email=user.email,
            email_verified=user.email_verified_at is not None,
            locale=user.locale,  # type: ignore[arg-type]  # DB check constraint guarantees the set
            trade_link=user.trade_link,
            trade_link_verdict=user.trade_link_verdict,  # type: ignore[arg-type]  # DB check
            trade_link_reason=user.trade_link_reason,  # type: ignore[arg-type]  # DB check
            trade_link_checked_at=user.trade_link_checked_at,
            roles=list(user.roles),
            created_at=user.created_at,
        )


class MePatchIn(BaseModel):
    """Editable profile fields; omitted = unchanged, ``email: null`` = clear."""

    model_config = ConfigDict(extra="forbid")

    locale: Literal["ru", "uz", "en"] | None = None
    email: EmailStr | None = None


class TradeLinkIn(BaseModel):
    """A pasted trade link."""

    model_config = ConfigDict(extra="forbid")

    url: str = Field(max_length=300)


class TradeLinkOut(BaseModel):
    """The saved link and its last check."""

    trade_link: str | None
    verdict: Literal["ok", "warn", "bad"] | None
    reason: Literal["invalid", "private", "trade_ban", "hold", "unavailable"] | None
    checked_at: datetime | None

    @classmethod
    def of(cls, user: User) -> TradeLinkOut:
        """Build from the ORM row."""
        return cls(
            trade_link=user.trade_link,
            verdict=user.trade_link_verdict,  # type: ignore[arg-type]  # DB check constraint
            reason=user.trade_link_reason,  # type: ignore[arg-type]  # DB check constraint
            checked_at=user.trade_link_checked_at,
        )
