"""The admin dashboard's numbers (M4b rulings R9, R10).

- a **sale** is an order paid in the window and not refunded; revenue = Σ ``price_uzs`` /
  Σ ``price_usd``; cost = Σ ``COALESCE(bought_units / 1000, cost_usd)`` (what the buy
  really cost, else what checkout agreed); margin = revenue − cost, and its percent of
  revenue;
- **refunds** = orders refunded in the window (by ``refunded_at``), count and Σ ``price_uzs``;
- **in flight** = ``paid | buying | trade_sent`` now; **attention** = open attentions now;
- one row per **Tashkent day** of the window, zeros included; the Waxpeer balance is the
  ``orders.health`` job's cached read.

The window starts at 00:00 Tashkent ``days − 1`` days before ``at`` and ends at ``at``.
Days are cut in Postgres (``AT TIME ZONE 'Asia/Tashkent'``, its own zone data); the window
start in Python uses the fixed UTC+5 offset (Tashkent keeps no daylight saving). A constant
number of queries whatever the window.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict
from redis.asyncio import Redis
from sqlalchemy import Date, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.modules.lisskins.api import LisskinsPurchase
from csmarket.modules.lisskins.api import cached_balance as lisskins_cached_balance
from csmarket.modules.orders.health import cached_balance
from csmarket.modules.orders.models import IN_FLIGHT, Order, SkinTrade
from csmarket.modules.skinslink.api import SkinslinkPurchase, skinslink_cached_balance

Days = Literal[1, 7, 30]
TASHKENT = timezone(timedelta(hours=5))
_ZERO = Decimal(0)


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True)


class Sales(_Frozen):
    count: int
    revenue_uzs: Decimal
    revenue_usd: Decimal
    cost_usd: Decimal
    margin_usd: Decimal
    margin_percent: Decimal


class Refunds(_Frozen):
    count: int
    amount_uzs: Decimal


class DayRow(_Frozen):
    day: date
    sales_count: int
    revenue_uzs: Decimal
    margin_usd: Decimal


class WaxpeerBalance(_Frozen):
    balance_usd: Decimal | None
    read_at: datetime | None


class SkinslinkBalance(_Frozen):
    available_usd: Decimal | None
    hold_usd: Decimal | None
    read_at: datetime | None


class LisskinsBalance(_Frozen):
    available_usd: Decimal | None
    locked_usd: Decimal | None
    read_at: datetime | None


class Dashboard(_Frozen):
    """Everything the dashboard shows for one window."""

    days: int
    since: datetime
    sales: Sales
    refunds: Refunds
    in_flight: int
    attention: int
    by_day: list[DayRow]
    waxpeer: WaxpeerBalance
    skinslink: SkinslinkBalance
    lisskins: LisskinsBalance


def window_start(at: datetime, days: int) -> datetime:
    """00:00 Tashkent, ``days − 1`` days before ``at``'s Tashkent day."""
    first = at.astimezone(TASHKENT).date() - timedelta(days=days - 1)
    return datetime.combine(first, time(0), tzinfo=TASHKENT)


async def _by_day(
    db: AsyncSession, since: datetime, at: datetime
) -> dict[date, tuple[int, Decimal, Decimal, Decimal]]:
    """Per Tashkent day: sales count, Σ soʻm, Σ USD, Σ cost."""
    day = cast(func.timezone("Asia/Tashkent", Order.paid_at), Date)
    cost = func.coalesce(SkinTrade.bought_units / Decimal(1000), Order.cost_usd)
    rows = await db.execute(
        select(
            day,
            func.count(),
            func.coalesce(func.sum(Order.price_uzs), 0),
            func.coalesce(func.sum(Order.price_usd), 0),
            func.coalesce(func.sum(cost), 0),
        )
        .select_from(Order)
        .outerjoin(SkinTrade, SkinTrade.order_id == Order.id)
        .where(Order.paid_at >= since, Order.paid_at <= at, Order.refunded_at.is_(None))
        .group_by(day)
    )
    return {
        d: (int(n), Decimal(str(uzs)), Decimal(str(usd)), Decimal(str(c)))
        for d, n, uzs, usd, c in rows.all()
    }


async def _refunds(db: AsyncSession, since: datetime, at: datetime) -> Refunds:
    n, amount = (
        await db.execute(
            select(func.count(), func.coalesce(func.sum(Order.price_uzs), 0)).where(
                Order.refunded_at >= since, Order.refunded_at <= at
            )
        )
    ).one()
    return Refunds(count=n, amount_uzs=Decimal(amount))


async def _now_counts(db: AsyncSession) -> tuple[int, int]:
    """Orders in flight and open attentions of every source, right now (one query)."""
    in_flight = (
        select(func.count()).select_from(Order).where(Order.status.in_(IN_FLIGHT)).scalar_subquery()
    )
    waiting = [
        select(func.count())
        .select_from(table)
        .where(table.attention_reason.is_not(None), table.resolved_at.is_(None))
        .scalar_subquery()
        for table in (SkinTrade, SkinslinkPurchase, LisskinsPurchase)
    ]
    a, b, c, d = (await db.execute(select(in_flight, *waiting))).one()
    return int(a), int(b) + int(c) + int(d)


def _sales(rows: dict[date, tuple[int, Decimal, Decimal, Decimal]]) -> Sales:
    count = sum(r[0] for r in rows.values())
    uzs = sum((r[1] for r in rows.values()), _ZERO)
    usd = sum((r[2] for r in rows.values()), _ZERO)
    cost = sum((r[3] for r in rows.values()), _ZERO)
    margin = usd - cost
    percent = (margin / usd * 100).quantize(Decimal("0.1")) if usd else _ZERO
    return Sales(
        count=count,
        revenue_uzs=uzs,
        revenue_usd=usd,
        cost_usd=cost,
        margin_usd=margin,
        margin_percent=percent,
    )


async def summary(db: AsyncSession, redis: Redis, *, days: Days, at: datetime) -> Dashboard:
    """The dashboard for the ``days`` Tashkent days ending at ``at``. Reads only."""
    since = window_start(at, days)
    rows = await _by_day(db, since, at)
    in_flight, attention = await _now_counts(db)
    balance, read_at = await cached_balance(redis)
    sl_available, sl_hold, sl_read_at = await skinslink_cached_balance(redis)
    ls_available, ls_locked, ls_read_at = await lisskins_cached_balance(redis)
    first = since.date()
    by_day = []
    for n in range(days):
        day = first + timedelta(days=n)
        count, uzs, usd, cost = rows.get(day, (0, _ZERO, _ZERO, _ZERO))
        by_day.append(DayRow(day=day, sales_count=count, revenue_uzs=uzs, margin_usd=usd - cost))
    return Dashboard(
        days=days,
        since=since,
        sales=_sales(rows),
        refunds=await _refunds(db, since, at),
        in_flight=in_flight,
        attention=attention,
        by_day=by_day,
        waxpeer=WaxpeerBalance(balance_usd=balance, read_at=read_at),
        skinslink=SkinslinkBalance(
            available_usd=sl_available, hold_usd=sl_hold, read_at=sl_read_at
        ),
        lisskins=LisskinsBalance(
            available_usd=ls_available, locked_usd=ls_locked, read_at=ls_read_at
        ),
    )


__all__ = [
    "Dashboard",
    "DayRow",
    "Days",
    "LisskinsBalance",
    "Refunds",
    "Sales",
    "SkinslinkBalance",
    "WaxpeerBalance",
    "summary",
]
