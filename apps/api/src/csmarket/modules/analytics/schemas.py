"""Wire shapes of ``/api/v1/admin/analytics`` (spec 2026-10-19-analytics).

Soʻm are whole digits, USD six places, percents one decimal — all strings; counts integers.
"""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel


class Money(BaseModel):
    """One amount in both currencies."""

    uzs: str
    usd: str


class Totals(BaseModel):
    """A period's headline numbers."""

    #: Counted orders (paid in the window, not refunded).
    orders: int
    revenue: Money
    cost: Money
    profit: Money
    #: ``profit.uzs / revenue.uzs``, one decimal; ``"0"`` without revenue.
    margin_percent: str
    #: The delivered part of ``profit.uzs`` and the part still in flight.
    earned_profit_uzs: str
    in_flight_profit_uzs: str
    in_flight_orders: int
    average_check_uzs: str
    buyback_profit_uzs: str
    buyback_profit_usd: str
    #: Orders refunded in the window (by their refund day).
    refunds: int
    refunds_uzs: str
    #: Users whose first paid order is in the window.
    new_buyers: int
    #: Orders' profit + buy-back profit, soʻm.
    gross_profit_uzs: str
    #: What partners were credited in the window (referrals), soʻm; not taken off the profit.
    partners_uzs: str = "0"


class DayOut(BaseModel):
    """One Tashkent day of a window."""

    day: date
    orders: int
    revenue_uzs: str
    earned_profit_uzs: str
    in_flight_profit_uzs: str
    buyback_profit_uzs: str


class Slice(BaseModel):
    """One key of a breakdown (a market, a channel, a payment, a category)."""

    key: str
    orders: int
    revenue_uzs: str
    profit_uzs: str
    profit_usd: str
    margin_percent: str


class FeeOut(BaseModel):
    """Kassa fees the buyers paid on top, per kassa (never subtracted from the profit)."""

    provider: str
    payments: int
    fee_uzs: str


class SkinOut(BaseModel):
    """A skin in the top list."""

    name: str
    image_url: str | None
    orders: int
    revenue_uzs: str
    profit_uzs: str


class CountOut(BaseModel):
    """Buyers of a kind and what they paid."""

    count: int
    revenue_uzs: str


class BuyerOut(BaseModel):
    """A top buyer."""

    id: str
    display_name: str | None
    avatar_url: str | None
    orders: int
    revenue_uzs: str
    profit_uzs: str


class BuyersOut(BaseModel):
    """New and returning buyers and the top 10 by revenue."""

    new: CountOut
    returning: CountOut
    top: list[BuyerOut]


class KeyCount(BaseModel):
    """A key and how many."""

    key: str
    count: int
    amount_uzs: str


class RefundsOut(BaseModel):
    """Orders refunded in the window."""

    count: int
    amount_uzs: str
    by_source: list[KeyCount]
    #: ``orders.failure_reason``; ``other`` when none was set.
    by_reason: list[KeyCount]


class BuybackOut(BaseModel):
    """The buy-back (выкуп) of the window — empty for the API channel."""

    count: int
    income_usd: str
    to_cards_uzs: str
    to_balances_uzs: str
    to_pay_uzs: str
    profit_uzs: str
    profit_usd: str


class BusinessOut(BaseModel):
    """The «Бизнес» tab: this period, the one before, by day, and every block."""

    since: date
    until: date
    channel: str
    totals: Totals
    previous: Totals
    by_day: list[DayOut]
    sources: list[Slice]
    channels: list[Slice]
    payments: list[Slice]
    kassa_fees: list[FeeOut]
    categories: list[Slice]
    top_skins: list[SkinOut]
    buyers: BuyersOut
    refunds: RefundsOut
    buyback: BuybackOut


class CalendarOut(BaseModel):
    """The «Календарь» tab: every day of a month."""

    month: str
    channel: str
    days: list[DayOut]


class LossOut(BaseModel):
    """A delivered order sold below its cost."""

    number: str
    name: str
    source: str
    paid_at: datetime
    revenue_uzs: str
    cost_uzs: str
    profit_uzs: str


class LossesOut(BaseModel):
    """«Продано в минус», worst first (at most 200)."""

    items: list[LossOut]
