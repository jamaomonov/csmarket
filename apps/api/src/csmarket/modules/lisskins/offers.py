"""LIS-SKINS' offers of one catalogue item, read from the snapshot (no external call)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.config import Settings
from csmarket.modules.lisskins.models import LisskinsOffer
from csmarket.modules.lisskins.snapshot import snapshot_fresh
from csmarket.modules.skins.api import Offer, offer_id_of


# Any: one stored sticker object (``export.Sticker`` as a dict).
def _sticker(raw: dict[str, Any]) -> dict[str, Any] | None:
    """A sticker as ``Offer.stickers`` carries it; the image is filtered on the way out
    (``skins.images.steam_image_only``)."""
    name, image, slot, wear = raw.get("name"), raw.get("image"), raw.get("slot"), raw.get("wear")
    if not isinstance(name, str):
        return None
    return {
        "name": name,
        "image": image if isinstance(image, str) else None,
        "slot": slot if isinstance(slot, int) and not isinstance(slot, bool) else None,
        "wear": float(wear)
        if isinstance(wear, int | float) and not isinstance(wear, bool)
        else None,
    }


async def offers_for(
    db: AsyncSession, skin_item_id: str, *, settings: Settings, now: datetime
) -> list[Offer]:
    """The item's LIS-SKINS lots by price; none while off, keyless or stale."""
    if not settings.lisskins_active or not await snapshot_fresh(db, settings=settings, now=now):
        return []
    rows = (
        await db.scalars(
            select(LisskinsOffer)
            .where(LisskinsOffer.skin_item_id == skin_item_id)
            .order_by(LisskinsOffer.price_units, LisskinsOffer.id)
        )
    ).all()
    return [
        Offer(
            offer_id=offer_id_of("lisskins", r.id),
            source="lisskins",
            price_units=r.price_units,
            float_value=None if r.float_value is None else float(r.float_value),
            paint_seed=r.paint_seed,
            stickers=[s for raw in r.stickers if isinstance(raw, dict) and (s := _sticker(raw))],
            inspect_url=r.inspect_url,
            asset_id=r.asset_id,
        )
        for r in rows
    ]


__all__ = ["offers_for"]
