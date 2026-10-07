"""Skinslink's offers of one catalogue item, read from the mirror (no external call)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.config import Settings
from csmarket.modules.skins.api import AppliedKind as Kind
from csmarket.modules.skins.api import Offer, applied_cards, offer_id_of
from csmarket.modules.skinslink.mirror import mirror_fresh
from csmarket.modules.skinslink.models import SkinslinkItem


async def offers_for(
    db: AsyncSession, skin_item_id: str, *, settings: Settings, now: datetime
) -> list[Offer]:
    """The item's Skinslink offers by price; none while inactive or the mirror is stale."""
    if not settings.skinslink_active or not await mirror_fresh(db, settings=settings, now=now):
        return []
    rows = (
        await db.scalars(
            select(SkinslinkItem)
            .where(SkinslinkItem.skin_item_id == skin_item_id)
            .order_by(SkinslinkItem.price_units, SkinslinkItem.id)
        )
    ).all()
    cards = await applied_cards(db, (ref for r in rows for ref in _refs(r)))
    return [
        Offer(
            offer_id=offer_id_of("skinslink", r.id),
            source="skinslink",
            price_units=r.price_units,
            float_value=None if r.float_value is None else float(r.float_value),
            paint_seed=r.paint_seed,
            stickers=_shown(r, cards),
            inspect_url=r.inspect_url,
            asset_id=r.id,
        )
        for r in rows
    ]


def _def_index(entry: object) -> int | None:
    value = entry.get("def_index") if isinstance(entry, dict) else None
    return value if isinstance(value, int) and not isinstance(value, bool) else None


# Any: the JSONB entries of a row.
def _applied(row: SkinslinkItem) -> tuple[tuple[Kind, list[Any]], ...]:
    return (("stickers", row.stickers or []), ("charms", row.keychains or []))


def _refs(row: SkinslinkItem) -> list[tuple[Kind, int]]:
    refs: list[tuple[Kind, int]] = []
    for kind, applied in _applied(row):
        refs += [(kind, d) for e in applied if (d := _def_index(e)) is not None]
    return refs


# Any: ``Offer.stickers`` entries (``{"name", "image", "slot", "wear"}``).
def _shown(
    row: SkinslinkItem, cards: dict[tuple[Kind, int], tuple[str, str | None]]
) -> list[dict[str, Any]]:
    """The listing's stickers, then its charms (no slot), as the item page shows them; one
    the catalogue does not know is left out."""
    shown: list[dict[str, Any]] = []
    for kind, applied in _applied(row):
        for entry in applied:
            card = cards.get((kind, d)) if (d := _def_index(entry)) is not None else None
            if card is None or not isinstance(entry, dict):
                continue
            wear, slot = entry.get("wear"), entry.get("slot")
            shown.append(
                {
                    "name": card[0],
                    "image": card[1],
                    "slot": slot if kind == "stickers" and isinstance(slot, int) else None,
                    "wear": float(wear) if isinstance(wear, int | float) else None,
                }
            )
    return shown


__all__ = ["offers_for"]
