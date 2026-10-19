"""The «Бизнес» headline: totals of a window and its days (spec 2026-10-19-analytics).

Orders come from :func:`.lines.order_lines` grouped per day in one statement; the buy-back
from ``sales.api.sales_pnl_between`` (site only: an API key never sells to us); refunds by
their own day; new buyers by their first paid order ever.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.modules.analytics.fmt import ZERO, dec, percent, som, usd
from csmarket.modules.analytics.lines import order_lines
from csmarket.modules.analytics.schemas import DayOut, Money, Totals
from csmarket.modules.analytics.window import Channel, Window
from csmarket.modules.orders.api import Order
from csmarket.modules.sales.api import SalesPnl, sales_pnl_between


class DayNums(BaseModel):
    """One day's order numbers, before formatting."""

    model_config = ConfigDict(frozen=True)

    orders: int = 0
    revenue_uzs: Decimal = ZERO
    revenue_usd: Decimal = ZERO
    cost_uzs: Decimal = ZERO
    cost_usd: Decimal = ZERO
    earned_uzs: Decimal = ZERO
    flying_uzs: Decimal = ZERO
    flying_orders: int = 0

    def __add__(self, other: DayNums) -> DayNums:
        return DayNums(**{k: getattr(self, k) + getattr(other, k) for k in DayNums.model_fields})


async def orders_by_day(db: AsyncSession, w: Window, channel: Channel) -> dict[date, DayNums]:
    """Per Tashkent day: counted orders, revenue, cost, earned and in-flight profit."""
    lines = order_lines(w, channel)
    earned = case((lines.c.earned, lines.c.profit_uzs), else_=0)
    flying = case((lines.c.earned, 0), else_=lines.c.profit_uzs)
    rows = await db.execute(
        select(
            lines.c.day,
            func.count(),
            func.sum(lines.c.revenue_uzs),
            func.sum(lines.c.revenue_usd),
            func.sum(lines.c.cost_uzs),
            func.sum(lines.c.cost_usd),
            func.sum(earned),
            func.sum(flying),
            func.count().filter(~lines.c.earned),
        ).group_by(lines.c.day)
    )
    return {
        day: DayNums(
            orders=int(n),
            revenue_uzs=dec(ru),
            revenue_usd=dec(rd),
            cost_uzs=dec(cu),
            cost_usd=dec(cd),
            earned_uzs=dec(e),
            flying_uzs=dec(f),
            flying_orders=int(fo),
        )
        for day, n, ru, rd, cu, cd, e, f, fo in rows.all()
    }


async def refunds(db: AsyncSession, w: Window, channel: Channel) -> tuple[int, Decimal]:
    """Orders refunded in the window (their refund day) and their price, soʻm."""
    stmt = select(func.count(), func.sum(Order.price_uzs)).where(
        Order.refunded_at >= w.start, Order.refunded_at < w.end
    )
    if channel != "all":
        stmt = stmt.where(Order.channel == channel)
    n, amount = (await db.execute(stmt)).one()
    return int(n), dec(amount)


async def new_buyers(db: AsyncSession, w: Window, channel: Channel) -> int:
    """Users whose first paid order ever is in the window (of ``channel`` when filtered)."""
    first = (
        select(Order.user_id, func.min(Order.paid_at).label("first"))
        .where(Order.paid_at.is_not(None))
        .group_by(Order.user_id)
        .subquery()
    )
    stmt = (
        select(func.count())
        .select_from(first)
        .where(first.c.first >= w.start, first.c.first < w.end)
    )
    if channel != "all":
        lines = order_lines(w, channel)
        stmt = stmt.where(first.c.user_id.in_(select(lines.c.user_id)))
    return int(await db.scalar(stmt) or 0)


async def buyback(db: AsyncSession, w: Window, channel: Channel) -> SalesPnl | None:
    """The window's buy-back P&L; ``None`` for the API channel (keys never sell to us)."""
    if channel == "api":
        return None
    return await sales_pnl_between(db, since=w.start, until=w.end)


def _totals(
    per_day: dict[date, DayNums], bb: SalesPnl | None, refunded: tuple[int, Decimal], new: int
) -> Totals:
    t = sum(per_day.values(), DayNums())
    bb_uzs = bb.profit_uzs if bb is not None else ZERO
    profit_uzs = t.revenue_uzs - t.cost_uzs
    return Totals(
        orders=t.orders,
        revenue=Money(uzs=som(t.revenue_uzs), usd=usd(t.revenue_usd)),
        cost=Money(uzs=som(t.cost_uzs), usd=usd(t.cost_usd)),
        profit=Money(uzs=som(profit_uzs), usd=usd(t.revenue_usd - t.cost_usd)),
        margin_percent=percent(profit_uzs, t.revenue_uzs),
        earned_profit_uzs=som(t.earned_uzs),
        in_flight_profit_uzs=som(t.flying_uzs),
        in_flight_orders=t.flying_orders,
        average_check_uzs=som(t.revenue_uzs / t.orders if t.orders else ZERO),
        buyback_profit_uzs=som(bb_uzs),
        buyback_profit_usd=usd(bb.profit_usd if bb is not None else ZERO),
        refunds=refunded[0],
        refunds_uzs=som(refunded[1]),
        new_buyers=new,
        gross_profit_uzs=som(profit_uzs + bb_uzs),
    )


def _days(w: Window, per_day: dict[date, DayNums], bb: SalesPnl | None) -> list[DayOut]:
    bb_by_day = {d.day: d.profit_uzs for d in bb.by_day} if bb is not None else {}
    out = []
    for day in w.dates():
        n = per_day.get(day, DayNums())
        out.append(
            DayOut(
                day=day,
                orders=n.orders,
                revenue_uzs=som(n.revenue_uzs),
                earned_profit_uzs=som(n.earned_uzs),
                in_flight_profit_uzs=som(n.flying_uzs),
                buyback_profit_uzs=som(bb_by_day.get(day, ZERO)),
            )
        )
    return out


async def summary(
    db: AsyncSession, w: Window, channel: Channel
) -> tuple[Totals, list[DayOut], SalesPnl | None]:
    """The window's totals, its days (zeros included) and its buy-back P&L, read once."""
    per_day = await orders_by_day(db, w, channel)
    bb = await buyback(db, w, channel)
    head = _totals(per_day, bb, await refunds(db, w, channel), await new_buyers(db, w, channel))
    return head, _days(w, per_day, bb), bb


async def totals(db: AsyncSession, w: Window, channel: Channel) -> Totals:
    """The window's headline numbers."""
    return (await summary(db, w, channel))[0]


async def by_day(db: AsyncSession, w: Window, channel: Channel) -> list[DayOut]:
    """Every day of the window, zeros included, with that day's buy-back profit (the
    calendar: no totals, no refunds, no buyers)."""
    return _days(w, await orders_by_day(db, w, channel), await buyback(db, w, channel))


__all__ = [
    "DayNums",
    "buyback",
    "by_day",
    "new_buyers",
    "orders_by_day",
    "refunds",
    "summary",
    "totals",
]
