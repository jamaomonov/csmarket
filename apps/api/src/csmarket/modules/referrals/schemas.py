"""Request and response bodies of ``referrals`` (spec 2026-10-27-referrals)."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from csmarket.modules.referrals.models import DEFAULT_TERM, PERCENT_MAX, PERCENT_MIN, TERM_MAX

Percent = Annotated[Decimal, Field(ge=PERCENT_MIN, le=PERCENT_MAX, decimal_places=1)]
Term = Annotated[int, Field(ge=1, le=TERM_MAX)]
RewardStatus = Literal["held", "credited", "cancelled"]


class PartnerIn(BaseModel):
    """«Сделать партнёром»: the account, its link code and terms."""

    model_config = ConfigDict(extra="forbid")

    user_id: str
    code: str = Field(max_length=64)
    percent: Percent
    #: Months a referred account earns for the partner; ``null`` = forever.
    term_months: Term | None = DEFAULT_TERM
    note: str | None = Field(default=None, max_length=1000)


class PartnerPatch(BaseModel):
    """Any subset of the terms; a field left out stays. ``term_months: null`` = forever."""

    model_config = ConfigDict(extra="forbid")

    code: str | None = Field(default=None, max_length=64)
    percent: Percent | None = None
    term_months: Term | None = None
    active: bool | None = None
    note: str | None = Field(default=None, max_length=1000)


class PartnerTotals(BaseModel):
    """A partner's numbers: link visits, accounts it brought, their purchases, its money."""

    visits: int = 0
    accounts: int = 0
    #: Rewards not cancelled: the purchases that earn.
    purchases: int = 0
    revenue_uzs: str = "0"
    held_uzs: str = "0"
    credited_uzs: str = "0"


class AdminPartnerOut(BaseModel):
    """One partner in the admin."""

    user_id: str
    display_name: str | None
    steam_id: str
    code: str
    percent: Decimal
    term_months: int | None
    active: bool
    note: str | None
    created_at: datetime
    totals: PartnerTotals


class AdminPartnersOut(BaseModel):
    """«Партнёры»: every partner, most revenue first."""

    items: list[AdminPartnerOut]


class MonthOut(BaseModel):
    """A partner's Tashkent month."""

    month: date
    visits: int
    accounts: int
    purchases: int
    revenue_uzs: str
    earned_uzs: str


class AdminRewardOut(BaseModel):
    """A reward as the admin sees it (with the order)."""

    order_number: str
    delivered_at: datetime
    base_uzs: str
    percent: Decimal
    amount_uzs: str
    status: RewardStatus
    available_at: datetime
    credited_at: datetime | None
    cancelled_reason: str | None


class AdminPartnerDetailOut(BaseModel):
    """A partner's page: terms, months and a page of rewards."""

    partner: AdminPartnerOut
    months: list[MonthOut]
    rewards: list[AdminRewardOut]
    next_cursor: str | None


class PartnerRefOut(BaseModel):
    """The partner an account came by."""

    user_id: str
    code: str
    display_name: str | None


class UserReferralOut(BaseModel):
    """The user card's referral line."""

    partner: PartnerRefOut | None
    attributed_at: datetime | None
    is_partner: bool
