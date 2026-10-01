"""Wire shapes for ``/api/v1/admin/users`` (the admin SPA's users and wallet pages).

Amounts are whole soʻm as digit strings (``core.money.wire_uzs``); an entry's amount is
signed (``+50000`` / ``-10000``), like the customer's history. The trade link is never
sent whole: ``trade_link_masked`` keeps ``partner`` and the token's last 2 characters.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from csmarket.core.money import wire_uzs
from csmarket.modules.users.api import User, mask_trade_link
from csmarket.modules.wallet.api import ADMIN_ADJUST_MAX, AdminEntry

#: An operator's free-text reason, trimmed.
Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=500)]
AdjustReason = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=4, max_length=500)
]
_MAX = int(ADMIN_ADJUST_MAX)


class AdminUserRow(BaseModel):
    """One line of the users list."""

    id: str
    display_name: str | None
    avatar_url: str | None
    steam_id: str
    roles: list[str]
    banned_at: datetime | None
    created_at: datetime
    #: Spendable soʻm, digits.
    balance_uzs: str


class AdminUsersOut(BaseModel):
    """A page of users, newest first, and the cursor for the next (``null`` on the last)."""

    items: list[AdminUserRow]
    next_cursor: str | None


class AdminUserDetail(BaseModel):
    """The account as an operator sees it: profile, roles, ban, trade-link state."""

    id: str
    steam_id: str
    display_name: str | None
    avatar_url: str | None
    email: str | None
    locale: Literal["ru", "uz", "en"]
    roles: list[str]
    banned_at: datetime | None
    ban_reason: str | None
    created_at: datetime
    #: ``…?partner=<id>&token=••••<last 2>``; ``null`` when none is saved.
    trade_link_masked: str | None
    trade_link_verdict: Literal["ok", "warn", "bad"] | None
    trade_link_reason: Literal["invalid", "private", "trade_ban", "hold", "unavailable"] | None
    trade_link_checked_at: datetime | None

    @classmethod
    def of(cls, user: User) -> AdminUserDetail:
        """Build from the ORM row."""
        return cls(
            id=user.id,
            steam_id=user.steam_id,
            display_name=user.display_name,
            avatar_url=user.avatar_url,
            email=user.email,
            locale=user.locale,  # type: ignore[arg-type]  # DB check constraint guarantees the set
            roles=list(user.roles),
            banned_at=user.banned_at,
            ban_reason=user.ban_reason,
            created_at=user.created_at,
            trade_link_masked=mask_trade_link(user.trade_link),
            trade_link_verdict=user.trade_link_verdict,  # type: ignore[arg-type]  # DB check
            trade_link_reason=user.trade_link_reason,  # type: ignore[arg-type]  # DB check
            trade_link_checked_at=user.trade_link_checked_at,
        )


class AdminEntryOut(BaseModel):
    """One balance-history line with who booked it and why."""

    id: str
    #: M4 adds ``purchase`` and ``refund``.
    kind: Literal["topup", "topup_reversal", "admin_adjust"]
    #: Signed whole soʻm: ``+50000`` credited, ``-10000`` debited.
    amount_uzs: str
    created_at: datetime
    #: The top-up's number for ``topup``/``topup_reversal``; else ``null``.
    reference_number: str | None
    #: ``payments`` or ``admin:<admin user id>``.
    actor: str | None
    #: The admin's reason for an ``admin_adjust``; else ``null``.
    reason: str | None

    @classmethod
    def of(cls, entry: AdminEntry) -> AdminEntryOut:
        """Build from a ledger :class:`AdminEntry`."""
        digits = wire_uzs(abs(entry.amount))
        return cls(
            id=entry.id,
            kind=entry.kind,  # type: ignore[arg-type]  # post() admits only TX_KINDS
            amount_uzs=f"+{digits}" if entry.amount > 0 else f"-{digits}",
            created_at=entry.created_at,
            reference_number=entry.reference_number,
            actor=entry.actor,
            reason=entry.reason,
        )


class AdminTopupOut(BaseModel):
    """One of the user's top-ups."""

    number: str
    amount_uzs: str
    status: Literal["pending", "succeeded", "expired", "reversed"]
    #: The kassa that took the money, else the first attempt's; ``null`` without one.
    provider: str | None
    created_at: datetime
    succeeded_at: datetime | None


class AdminUserCard(BaseModel):
    """Everything the user page shows: the account, its balance, the latest 20 of each."""

    user: AdminUserDetail
    balance_uzs: str
    entries: list[AdminEntryOut]
    topups: list[AdminTopupOut]


class AdminReasonIn(BaseModel):
    """Ban or unban: why, in a few words."""

    model_config = ConfigDict(extra="forbid")

    reason: Reason


class AdminAdjustIn(BaseModel):
    """Credit (``amount_uzs > 0``) or claw back (``< 0``) the user's balance."""

    model_config = ConfigDict(extra="forbid")

    #: Whole soʻm, a JSON integer, non-zero, at most 100 000 000 either way.
    amount_uzs: Annotated[int, Field(strict=True, ge=-_MAX, le=_MAX)]
    reason: AdjustReason

    @field_validator("amount_uzs")
    @classmethod
    def _not_zero(cls, value: int) -> int:
        if value == 0:
            msg = "amount_uzs must not be 0"
            raise ValueError(msg)
        return value


__all__ = [
    "AdminAdjustIn",
    "AdminEntryOut",
    "AdminReasonIn",
    "AdminTopupOut",
    "AdminUserCard",
    "AdminUserDetail",
    "AdminUserRow",
    "AdminUsersOut",
]
