"""One substitute rule for every buy path (specs 2026-10-06 §6, 2026-10-07 §5).

A refused offer is replaced at most once by the cheapest other offer of the item, of any
source, within the order's ceiling (``order_substitute_ceiling`` over the agreed cost).
:func:`next_offer` finds it — Skinslink's and LIS-SKINS' offers from our own tables, and
Waxpeer's listings through the item page's cached, budgeted read while Waxpeer buying is
on. :func:`switch_source` hands the order to another source's path: its pending buy is
keyed ``<order id>:2``, the key that tells that path the substitute was already taken.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.clock import now
from csmarket.core.config import Settings
from csmarket.core.redis import get_redis
from csmarket.modules.lisskins.api import LisskinsPurchase
from csmarket.modules.lisskins.api import offers_for as lisskins_offers
from csmarket.modules.orders.buy_rules import TradeSearch
from csmarket.modules.orders.models import Order, SkinTrade
from csmarket.modules.skins.api import (
    Listing,
    Offer,
    SkinItem,
    TradeClient,
    from_listing,
    listings_budget,
    listings_for,
    merge_offers,
    parse_offer_id,
)
from csmarket.modules.skinslink.api import SkinslinkPurchase
from csmarket.modules.skinslink.api import offers_for as skinslink_offers


async def stored_offers(
    db: AsyncSession, skin_item_id: str, *, settings: Settings, now: datetime
) -> list[Offer]:
    """Skinslink's and LIS-SKINS' offers of the item (database reads only)."""
    return [
        *await skinslink_offers(db, skin_item_id, settings=settings, now=now),
        *await lisskins_offers(db, skin_item_id, settings=settings, now=now),
    ]


async def next_offer(
    db: AsyncSession,
    *,
    skin_item_id: str,
    ceiling: int,
    tried: set[str],
    settings: Settings,
    waxpeer: TradeClient | None,
) -> Offer | None:
    """The cheapest offer of the item not in ``tried``, at most ``ceiling`` units, any source.

    Ends the read transaction before the Waxpeer read (no lock across an external call).
    """
    item = await db.get(SkinItem, skin_item_id)
    if item is not None:
        db.expunge(item)  # read below with no transaction open
    extra = await stored_offers(db, skin_item_id, settings=settings, now=now())
    await db.commit()
    rows: list[Listing] = []
    if item is not None and waxpeer is not None and settings.waxpeer_buy_enabled:
        rows, _ = await listings_for(
            item,
            client=TradeSearch(waxpeer),
            redis=get_redis(),
            budget_per_minute=listings_budget(settings),
        )
    offers = merge_offers([from_listing(r) for r in rows], extra)
    return next(
        (o for o in offers if o.offer_id not in tried and 0 < o.price_units <= ceiling), None
    )


def pending_buy(
    order: Order, *, units: int, key: str
) -> SkinTrade | SkinslinkPurchase | LisskinsPurchase:
    """The row that holds ``order``'s pending buy at its source, keyed ``key`` (Skinslink's
    ``merchant_tx_id``, LIS-SKINS' ``custom_id``; Waxpeer's ``project_id`` is the order id,
    which its lookup searches by; an older Waxpeer order carries no ``offer_id``)."""
    if order.source == "skinslink":
        _, raw = parse_offer_id(order.offer_id or "")
        return SkinslinkPurchase(
            order_id=order.id, merchant_tx_id=key, asset_id=raw, paid_units=units, buy_pending=True
        )
    if order.source == "lisskins":
        _, raw = parse_offer_id(order.offer_id or "")
        return LisskinsPurchase(
            order_id=order.id, custom_id=key, skin_id=int(raw), paid_units=units, buy_pending=True
        )
    return SkinTrade(
        order_id=order.id,
        project_id=order.id,
        listing_id=order.listing_id,
        paid_units=units,
        buy_pending=True,
        seller={},
    )


async def switch_source(db: AsyncSession, order: Order, offer: Offer) -> None:
    """Hand the locked ``order`` to ``offer``'s (other) source: the refused purchase row goes,
    a pending one keyed ``<order id>:2`` takes its place, and the order is due at once. The
    caller commits."""
    for table in (SkinslinkPurchase, LisskinsPurchase):
        await db.execute(delete(table).where(table.order_id == order.id))
    order.source, order.offer_id, order.listing_id = offer.source, offer.offer_id, offer.listing_id
    db.add(pending_buy(order, units=offer.price_units, key=f"{order.id}:2"))
    order.next_check_at = None


__all__ = ["next_offer", "pending_buy", "stored_offers", "switch_source"]
