"""The «Бизнес» breakdowns: by market, channel, payment, category, top skins, kassa fees.

Each is one grouped statement over :func:`.lines.order_lines`, biggest revenue first.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import ColumnElement, Subquery, case, func, literal, select
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.modules.analytics.fmt import dec, percent, som, usd
from csmarket.modules.analytics.lines import order_lines
from csmarket.modules.analytics.schemas import FeeOut, SkinOut, Slice
from csmarket.modules.analytics.window import Channel, Window
from csmarket.modules.payments.api import Payment
from csmarket.modules.public_api.api import ApiKey
from csmarket.modules.users.api import User

TOP = 10


# Any: the grouping key's SQL type differs per block (text of a column or a CASE).
async def _slices(
    db: AsyncSession, lines: Subquery, key: ColumnElement[Any], *joins: Any
) -> list[Slice]:
    stmt = select(
        func.coalesce(key, literal("other")).label("key"),
        func.count(),
        func.sum(lines.c.revenue_uzs),
        func.sum(lines.c.profit_uzs),
        func.sum(lines.c.profit_usd),
    ).select_from(lines)
    for table, on in joins:
        stmt = stmt.outerjoin(table, on)
    rows = await db.execute(stmt.group_by("key").order_by(func.sum(lines.c.revenue_uzs).desc()))
    return [
        Slice(
            key=str(k),
            orders=int(n),
            revenue_uzs=som(dec(rev)),
            profit_uzs=som(dec(profit)),
            profit_usd=usd(dec(profit_usd)),
            margin_percent=percent(dec(profit), dec(rev)),
        )
        for k, n, rev, profit, profit_usd in rows.all()
    ]


async def by_source(db: AsyncSession, w: Window, channel: Channel) -> list[Slice]:
    """Per market: ``waxpeer``, ``skinslink``, ``lisskins``."""
    lines = order_lines(w, channel)
    return await _slices(db, lines, lines.c.source)


async def by_channel(db: AsyncSession, w: Window, channel: Channel) -> list[Slice]:
    """«Сайт», and each API key by its owner's name."""
    lines = order_lines(w, channel)
    key = case(
        (lines.c.channel == "site", literal("Сайт")),
        else_=func.coalesce(User.display_name, literal("API")),
    )
    return await _slices(
        db,
        lines,
        key,
        (ApiKey, ApiKey.id == lines.c.api_key_id),
        (User, User.id == ApiKey.user_id),
    )


async def by_payment(db: AsyncSession, w: Window, channel: Channel) -> list[Slice]:
    """Per ``orders.paid_with``: wallet, usd_wallet, click, payme, uzum."""
    lines = order_lines(w, channel)
    return await _slices(db, lines, lines.c.paid_with)


async def by_category(db: AsyncSession, w: Window, channel: Channel) -> list[Slice]:
    """Per catalogue category (knives, gloves, rifles…)."""
    lines = order_lines(w, channel)
    return await _slices(db, lines, lines.c.category)


async def top_skins(db: AsyncSession, w: Window, channel: Channel) -> list[SkinOut]:
    """The :data:`TOP` skins by profit, best first."""
    lines = order_lines(w, channel)
    profit = func.sum(lines.c.profit_uzs)
    rows = await db.execute(
        select(
            lines.c.name,
            func.max(lines.c.image_url),
            func.count(),
            func.sum(lines.c.revenue_uzs),
            profit,
        )
        .group_by(lines.c.name)
        .order_by(profit.desc(), lines.c.name)
        .limit(TOP)
    )
    return [
        SkinOut(
            name=name,
            image_url=image,
            orders=int(n),
            revenue_uzs=som(dec(rev)),
            profit_uzs=som(dec(p)),
        )
        for name, image, n, rev, p in rows.all()
    ]


async def kassa_fees(db: AsyncSession, w: Window) -> list[FeeOut]:
    """Fees buyers paid on top per kassa: succeeded payments of the window (top-ups too)."""
    rows = await db.execute(
        select(Payment.provider, func.count(), func.sum(Payment.fee_uzs))
        .where(
            Payment.status == "succeeded",
            Payment.succeeded_at >= w.start,
            Payment.succeeded_at < w.end,
            Payment.fee_uzs > 0,
        )
        .group_by(Payment.provider)
        .order_by(Payment.provider)
    )
    return [FeeOut(provider=p, payments=int(n), fee_uzs=som(dec(f))) for p, n, f in rows.all()]


__all__ = [
    "by_category",
    "by_channel",
    "by_payment",
    "by_source",
    "kassa_fees",
    "top_skins",
]
