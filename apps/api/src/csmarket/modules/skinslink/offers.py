"""Skinslink's offers of one catalogue item, read from the mirror (no external call)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.config import Settings
from csmarket.modules.skins.api import Offer, offer_id_of
from csmarket.modules.skinslink.mirror import mirror_fresh
from csmarket.modules.skinslink.models import SkinslinkItem


async def offers_for(
    db: AsyncSession, skin_item_id: str, *, settings: Settings, now: datetime
) -> list[Offer]:
    """The item's Skinslink offers by price; none while inactive or the mirror is stale."""
    if not settings.skinslink_active or not await mirror_fresh(db, settings=settings, now=now):
        return []
    rows = await db.scalars(
        select(SkinslinkItem)
        .where(SkinslinkItem.skin_item_id == skin_item_id)
        .order_by(SkinslinkItem.price_units, SkinslinkItem.id)
    )
    return [
        Offer(
            offer_id=offer_id_of("skinslink", r.id),
            source="skinslink",
            price_units=r.price_units,
            float_value=None if r.float_value is None else float(r.float_value),
            paint_seed=r.paint_seed,
            stickers=[],
            inspect_url=r.inspect_url,
            asset_id=r.id,
        )
        for r in rows.all()
    ]


__all__ = ["offers_for"]
