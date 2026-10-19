"""The «Покупатели» and «Возвраты» blocks (spec 2026-10-19-analytics).

A buyer is **new** when their first paid order ever is in the window, **returning** when they
paid before it too.
"""

from __future__ import annotations

from sqlalchemy import func, literal, select
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.modules.analytics.blocks import TOP
from csmarket.modules.analytics.fmt import dec, som
from csmarket.modules.analytics.lines import order_lines, revenue_uzs_sql
from csmarket.modules.analytics.schemas import BuyerOut, BuyersOut, CountOut, KeyCount, RefundsOut
from csmarket.modules.analytics.window import Channel, Window
from csmarket.modules.fx.api import FxSnapshot
from csmarket.modules.orders.api import Order
from csmarket.modules.users.api import User


async def buyers(db: AsyncSession, w: Window, channel: Channel) -> BuyersOut:
    """New and returning buyers of the window, and the top :data:`TOP` by revenue."""
    lines = order_lines(w, channel)
    first = (
        select(Order.user_id, func.min(Order.paid_at).label("first"))
        .where(Order.paid_at.is_not(None))
        .group_by(Order.user_id)
        .subquery()
    )
    per_user = (
        select(
            lines.c.user_id,
            func.count().label("orders"),
            func.sum(lines.c.revenue_uzs).label("revenue"),
            func.sum(lines.c.profit_uzs).label("profit"),
        )
        .group_by(lines.c.user_id)
        .subquery()
    )
    is_new = first.c.first >= w.start
    split = await db.execute(
        select(is_new, func.count(), func.sum(per_user.c.revenue))
        .select_from(per_user)
        .join(first, first.c.user_id == per_user.c.user_id)
        .group_by(is_new)
    )
    counts = {bool(new): CountOut(count=int(n), revenue_uzs=som(dec(r))) for new, n, r in split}
    top = await db.execute(
        select(
            per_user.c.user_id,
            User.display_name,
            User.avatar_url,
            per_user.c.orders,
            per_user.c.revenue,
            per_user.c.profit,
        )
        .join(User, User.id == per_user.c.user_id)
        .order_by(per_user.c.revenue.desc(), per_user.c.user_id)
        .limit(TOP)
    )
    empty = CountOut(count=0, revenue_uzs="0")
    return BuyersOut(
        new=counts.get(True, empty),
        returning=counts.get(False, empty),
        top=[
            BuyerOut(
                id=uid,
                display_name=name,
                avatar_url=avatar,
                orders=int(n),
                revenue_uzs=som(dec(rev)),
                profit_uzs=som(dec(p)),
            )
            for uid, name, avatar, n, rev, p in top.all()
        ],
    )


async def refunds_block(db: AsyncSession, w: Window, channel: Channel) -> RefundsOut:
    """Orders refunded in the window (their refund day), by market and by reason."""
    revenue = revenue_uzs_sql()
    where = [Order.refunded_at >= w.start, Order.refunded_at < w.end]
    if channel != "all":
        where.append(Order.channel == channel)

    async def grouped(column: object) -> list[KeyCount]:
        key = func.coalesce(column, literal("other")).label("key")
        rows = await db.execute(
            select(key, func.count(), func.sum(revenue))
            .select_from(Order)
            .select_from(Order)
            .join(FxSnapshot, FxSnapshot.id == Order.fx_snapshot_id)
            .where(*where)
            .group_by("key")
            .order_by(func.count().desc(), "key")
        )
        return [KeyCount(key=str(k), count=int(n), amount_uzs=som(dec(a))) for k, n, a in rows]

    n, amount = (
        await db.execute(
            select(func.count(), func.sum(revenue))
            .select_from(Order)
            .select_from(Order)
            .join(FxSnapshot, FxSnapshot.id == Order.fx_snapshot_id)
            .where(*where)
        )
    ).one()
    return RefundsOut(
        count=int(n),
        amount_uzs=som(dec(amount)),
        by_source=await grouped(Order.source),
        by_reason=await grouped(Order.failure_reason),
    )


__all__ = ["buyers", "refunds_block"]
