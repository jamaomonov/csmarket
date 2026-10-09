"""Wire shapes for ``/api/v1/admin/users`` (the admin SPA's users and wallet pages).

Amounts are whole soʻm as digit strings (``core.money.wire_uzs``); an entry's amount is
signed (``+50000`` / ``-10000``), like the customer's history. The trade link is never
sent whole: ``trade_link_masked`` keeps ``partner`` and the token's last 2 characters.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from csmarket.core.money import wire_usd, wire_uzs
from csmarket.modules.admin.orders_schemas import AdminOrderRow
from csmarket.modules.users.api import User, mask_trade_link
from csmarket.modules.wallet.api import (
    ADMIN_ADJUST_MAX,
    ADMIN_ADJUST_USD_MAX,
    AdminEntry,
    Currency,
)

#: An operator's free-text reason, trimmed.
Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=500)]
AdjustReason = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=4, max_length=500)
]
_MAX = int(ADMIN_ADJUST_MAX)
_MAX_USD_UNITS = int(ADMIN_ADJUST_USD_MAX)


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
    kind: Literal[
        "topup",
        "topup_reversal",
        "admin_adjust",
        "purchase",
        "refund",
        "sale_credit",
        "payout_return",
        "fx_convert",
        "admin_adjust_usd",
    ]
    currency: Currency = "UZS"
    #: Signed whole soʻm: ``+50000`` credited, ``-10000`` debited; ``"0"`` on a dollar line.
    amount_uzs: str
    #: Signed dollars (``+250.000``) on a dollar line; ``null`` on a soʻm line.
    amount_usd: str | None = None
    created_at: datetime
    #: The top-up's number for ``topup``/``topup_reversal``, the order's number for
    #: ``purchase``/``refund``, the sale's number for ``sale_credit``/``payout_return``; else
    #: ``null``.
    reference_number: str | None
    #: ``payments`` or ``admin:<admin user id>``.
    actor: str | None
    #: The admin's reason for an ``admin_adjust``; else ``null``.
    reason: str | None

    @classmethod
    def of(cls, entry: AdminEntry, currency: Currency = "UZS") -> AdminEntryOut:
        """Build from a ledger :class:`AdminEntry` of the ``currency`` wallet."""
        sign = "+" if entry.amount > 0 else "-"
        usd = currency == "USD"
        return cls(
            id=entry.id,
            kind=entry.kind,  # type: ignore[arg-type]  # post() admits only TX_KINDS
            currency=currency,
            amount_uzs="0" if usd else f"{sign}{wire_uzs(abs(entry.amount))}",
            amount_usd=f"{sign}{wire_usd(abs(entry.amount))}" if usd else None,
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
    #: Newest first; open one at ``/admin/orders/{number}``.
    orders: list[AdminOrderRow]
    #: The USD wallet is switched on for this user.
    usd_wallet_enabled: bool
    #: Spendable dollars, three decimals (``"250.000"``).
    balance_usd: str
    #: The latest 20 dollar lines, newest first (``currency == "USD"``, ``amount_usd`` set).
    usd_entries: list[AdminEntryOut]


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


class AdminUsdSwitchIn(BaseModel):
    """Switch the USD wallet on or off, and why."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool
    reason: Reason


class AdminAdjustUsdIn(BaseModel):
    """Credit (``> 0``) or claw back (``< 0``) the user's dollars."""

    model_config = ConfigDict(extra="forbid")

    #: Dollars as a string, at most 3 decimals, non-zero, ``|x| <= 100000``: ``"250.000"``.
    amount_usd: Annotated[str, StringConstraints(pattern=r"^-?\d{1,7}(\.\d{1,3})?$")]
    reason: AdjustReason

    @field_validator("amount_usd")
    @classmethod
    def _bounds(cls, value: str) -> str:
        units = Decimal(value) * 1000
        if units == 0:
            msg = "amount_usd must not be 0"
            raise ValueError(msg)
        if abs(units) > _MAX_USD_UNITS:
            msg = "amount_usd is out of range"
            raise ValueError(msg)
        return value

    @property
    def units(self) -> int:
        """The amount in milli-USD units (integral by the pattern)."""
        return int(Decimal(self.amount_usd) * 1000)


__all__ = [
    "AdminAdjustIn",
    "AdminAdjustUsdIn",
    "AdminEntryOut",
    "AdminReasonIn",
    "AdminTopupOut",
    "AdminUsdSwitchIn",
    "AdminUserCard",
    "AdminUserDetail",
    "AdminUserRow",
    "AdminUsersOut",
]
