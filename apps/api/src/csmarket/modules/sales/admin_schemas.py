"""Admin wire shapes of ``sales`` (spec 2026-10-08 §7). Money as strings; a card by its last
four — the full number only in :class:`RevealOut`, which is never stored as a replay."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from csmarket.modules.sales.rules import CardType, PayoutTo, SaleSettings
from csmarket.modules.sales.schemas import PayoutStatusOut, SaleStatusOut


class AdminUserOut(BaseModel):
    """A user as the admin lists name them."""

    id: str
    display_name: str | None


class PayoutRowOut(BaseModel):
    """A payout request in the queue."""

    id: str
    sale_number: str
    user: AdminUserOut
    card_type: CardType
    #: ``•••• 9015``.
    card_masked: str
    amount_uzs: str
    fee_uzs: str
    status: PayoutStatusOut
    #: Since when it is payable.
    to_pay_at: datetime | None
    paid_at: datetime | None
    created_at: datetime


class PayoutCountsOut(BaseModel):
    """Requests per status (the tabs)."""

    waiting_hold: int = 0
    to_pay: int = 0
    paid: int = 0
    rejected: int = 0
    canceled: int = 0


class PayoutsPageOut(BaseModel):
    """One page of a status tab, every tab's count and the next cursor."""

    items: list[PayoutRowOut]
    counts: PayoutCountsOut
    next_cursor: str | None


class AdminSaleItemOut(BaseModel):
    """One skin of a sale with both prices."""

    asset_id: str
    name: str
    #: Skinslink's price.
    price_usd: str
    #: Ours.
    price_uzs: str


class AdminSaleRowOut(BaseModel):
    """A sale as the admin list shows it."""

    number: str
    status: SaleStatusOut
    user: AdminUserOut
    payout_to: PayoutTo
    quoted_usd: str
    payout_uzs: str
    margin_usd: str
    attention_reason: str | None
    created_at: datetime


class AdminSalesPageOut(BaseModel):
    """One page of sales and the next cursor."""

    items: list[AdminSaleRowOut]
    next_cursor: str | None


class AdminSaleOut(BaseModel):
    """A sale's page: Skinslink's side, our payout, our margin."""

    number: str
    status: SaleStatusOut
    user: AdminUserOut
    payout_to: PayoutTo
    card_type: CardType | None
    card_masked: str | None
    quoted_usd: str
    amount_usd: str | None
    items_uzs: str
    bonus_uzs: str
    fee_uzs: str
    payout_uzs: str
    rate: str
    margin_usd: str
    trade_id: int | None
    trade_offer_id: str | None
    bot_name: str | None
    offer_expiry_at: datetime | None
    hold_end_at: datetime | None
    fail_reason: str | None
    attention_reason: str | None
    credited_at: datetime | None
    created_at: datetime
    updated_at: datetime
    items: list[AdminSaleItemOut]
    payout: PayoutRowOut | None


class PayoutDetailOut(BaseModel):
    """A request's page: the request, its sale, the seller's history, what may be done."""

    request: PayoutRowOut
    note: str | None
    reject_reason: str | None
    decided_by: AdminUserOut | None
    sale: AdminSaleOut
    history_sales: list[AdminSaleRowOut]
    history_payouts: list[PayoutRowOut]
    #: «Выплачено» and «Отклонить» are possible (the request is ``to_pay``).
    can_decide: bool


class RevealIn(BaseModel):
    """Why the admin asks for the number: to look at it or to copy it."""

    purpose: Literal["show", "copy"]


class RevealOut(BaseModel):
    """The full card number, once, in this body only."""

    #: The full card number. PII: shown to the admin, never stored or logged.
    number: str


class PaidIn(BaseModel):
    """«Выплачено» with an optional note."""

    note: str | None = Field(default=None, max_length=500)


class RejectIn(BaseModel):
    """«Отклонить» with the reason (required)."""

    reason: str = Field(min_length=1, max_length=500)


class SaleSettingsOut(BaseModel):
    """The saved document, who saved it and when, and the rate now."""

    settings: SaleSettings
    updated_at: datetime | None
    updated_by: AdminUserOut | None
    #: The CBU rate now (no uplift), before ``rate_cut_pct``; ``null`` without one.
    rate_uzs: str | None
