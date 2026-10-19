"""The three analytics answers, assembled from the blocks and cached (routes only dispatch)."""

from __future__ import annotations

from datetime import date

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.modules.analytics.blocks import (
    by_category,
    by_channel,
    by_payment,
    by_source,
    kassa_fees,
    top_skins,
)
from csmarket.modules.analytics.business import by_day, summary, totals
from csmarket.modules.analytics.buyers import buyers, refunds_block
from csmarket.modules.analytics.cache import cache_key, cached
from csmarket.modules.analytics.fmt import som, usd
from csmarket.modules.analytics.losses import losses
from csmarket.modules.analytics.schemas import (
    BusinessOut,
    BuybackOut,
    CalendarOut,
    LossesOut,
)
from csmarket.modules.analytics.window import Channel, Window
from csmarket.modules.sales.api import SalesPnl


def _buyback(bb: SalesPnl | None) -> BuybackOut:
    if bb is None:
        return BuybackOut(
            count=0,
            income_usd=usd(0),
            to_cards_uzs="0",
            to_balances_uzs="0",
            to_pay_uzs="0",
            profit_uzs="0",
            profit_usd=usd(0),
        )
    return BuybackOut(
        count=bb.count,
        income_usd=usd(bb.income_usd),
        to_cards_uzs=som(bb.to_cards_uzs),
        to_balances_uzs=som(bb.to_balances_uzs),
        to_pay_uzs=som(bb.to_pay_uzs),
        profit_uzs=som(bb.profit_uzs),
        profit_usd=usd(bb.profit_usd),
    )


async def _business(db: AsyncSession, w: Window, channel: Channel) -> BusinessOut:
    head, days, bb = await summary(db, w, channel)
    return BusinessOut(
        since=w.since,
        until=w.until,
        channel=channel,
        totals=head,
        previous=await totals(db, w.previous(), channel),
        by_day=days,
        sources=await by_source(db, w, channel),
        channels=await by_channel(db, w, channel),
        payments=await by_payment(db, w, channel),
        kassa_fees=await kassa_fees(db, w),
        categories=await by_category(db, w, channel),
        top_skins=await top_skins(db, w, channel),
        buyers=await buyers(db, w, channel),
        refunds=await refunds_block(db, w, channel),
        buyback=_buyback(bb),
    )


async def business(
    db: AsyncSession, redis: Redis, w: Window, channel: Channel, today: date
) -> BusinessOut:
    """The «Бизнес» tab for ``w``."""
    return await cached(
        redis,
        cache_key("business", w, channel),
        w.ttl(today),
        BusinessOut,
        lambda: _business(db, w, channel),
    )


async def calendar(
    db: AsyncSession, redis: Redis, w: Window, channel: Channel, today: date
) -> CalendarOut:
    """The «Календарь» tab: ``w`` is a whole month."""

    async def build() -> CalendarOut:
        return CalendarOut(
            month=w.since.strftime("%Y-%m"), channel=channel, days=await by_day(db, w, channel)
        )

    return await cached(redis, cache_key("calendar", w, channel), w.ttl(today), CalendarOut, build)


async def losses_of(
    db: AsyncSession, redis: Redis, w: Window, channel: Channel, today: date
) -> LossesOut:
    """«Продано в минус» for ``w``."""
    return await cached(
        redis,
        cache_key("losses", w, channel),
        w.ttl(today),
        LossesOut,
        lambda: losses(db, w, channel),
    )


__all__ = ["business", "calendar", "losses_of"]
