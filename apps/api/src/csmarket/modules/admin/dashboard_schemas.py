"""DTOs for ``GET /admin/dashboard`` (M4b R9). Money is a string in transit."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel

from csmarket.modules.orders.api import Dashboard


def _money(value: Decimal) -> str:
    """``Decimal('26.500000')`` → ``26.5``; ``Decimal('0')`` → ``0``."""
    text = format(value.normalize(), "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


class SalesOut(BaseModel):
    count: int
    revenue_uzs: str
    revenue_usd: str
    cost_usd: str
    margin_usd: str
    #: Margin as a percent of revenue (USD), one decimal.
    margin_percent: str


class RefundsOut(BaseModel):
    count: int
    amount_uzs: str


class DayOut(BaseModel):
    #: The Tashkent calendar day.
    day: date
    sales_count: int
    revenue_uzs: str
    margin_usd: str


class WaxpeerOut(BaseModel):
    #: The last good read by the health job; ``null`` when unknown (none in the last hour).
    balance_usd: str | None
    read_at: datetime | None


class SkinslinkOut(BaseModel):
    #: The last good read by the balance job; ``null`` when unknown (none in the last hour).
    available_usd: str | None
    hold_usd: str | None
    read_at: datetime | None


class LisskinsOut(BaseModel):
    #: The last good read by the balance job; ``null`` when unknown (none in the last hour).
    available_usd: str | None
    locked_usd: str | None
    read_at: datetime | None


class DashboardOut(BaseModel):
    """Sales, margin and refunds for today / 7 / 30 Tashkent days, plus what needs a look."""

    days: int
    since: datetime
    sales: SalesOut
    refunds: RefundsOut
    in_flight: int
    attention: int
    by_day: list[DayOut]
    waxpeer: WaxpeerOut
    skinslink: SkinslinkOut
    lisskins: LisskinsOut

    @classmethod
    def of(cls, d: Dashboard) -> DashboardOut:
        """Strings for the money."""
        s = d.sales
        return cls(
            days=d.days,
            since=d.since,
            sales=SalesOut(
                count=s.count,
                revenue_uzs=_money(s.revenue_uzs),
                revenue_usd=_money(s.revenue_usd),
                cost_usd=_money(s.cost_usd),
                margin_usd=_money(s.margin_usd),
                margin_percent=_money(s.margin_percent),
            ),
            refunds=RefundsOut(count=d.refunds.count, amount_uzs=_money(d.refunds.amount_uzs)),
            in_flight=d.in_flight,
            attention=d.attention,
            by_day=[
                DayOut(
                    day=r.day,
                    sales_count=r.sales_count,
                    revenue_uzs=_money(r.revenue_uzs),
                    margin_usd=_money(r.margin_usd),
                )
                for r in d.by_day
            ],
            waxpeer=WaxpeerOut(
                balance_usd=None
                if d.waxpeer.balance_usd is None
                else _money(d.waxpeer.balance_usd),
                read_at=d.waxpeer.read_at,
            ),
            skinslink=SkinslinkOut(
                available_usd=None
                if d.skinslink.available_usd is None
                else _money(d.skinslink.available_usd),
                hold_usd=None if d.skinslink.hold_usd is None else _money(d.skinslink.hold_usd),
                read_at=d.skinslink.read_at,
            ),
            lisskins=LisskinsOut(
                available_usd=None
                if d.lisskins.available_usd is None
                else _money(d.lisskins.available_usd),
                locked_usd=None if d.lisskins.locked_usd is None else _money(d.lisskins.locked_usd),
                read_at=d.lisskins.read_at,
            ),
        )
