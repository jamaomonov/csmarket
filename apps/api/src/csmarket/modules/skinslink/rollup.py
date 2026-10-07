"""Skinslink's stock rolled up onto ``skin_items`` (spec 2026-10-06 §4).

Each price tick writes, per catalogue item, the cheapest Skinslink price and how many it has
(``skinslink_min_units`` / ``skinslink_count``); an item with Skinslink stock is on sale even
when Waxpeer has none. Disabled or a stale mirror → every roll-up is cleared and items that
only Skinslink kept on sale go inactive. ``skins.repricing`` then prices from the cheaper side.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Select, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.config import Settings
from csmarket.modules.skins.api import SkinItem
from csmarket.modules.skinslink.mirror import mirror_fresh
from csmarket.modules.skinslink.models import SkinslinkItem


def _rowcount(result: object) -> int:
    """``rowcount`` lives on CursorResult; async ``execute`` is typed as Result."""
    return int(getattr(result, "rowcount", 0) or 0)


async def _clear(db: AsyncSession, *, keep: Select[tuple[int | None]] | None = None) -> int:
    """Clear the roll-up of every item with one (except ``keep``); re-derive ``active``."""
    stmt = update(SkinItem).where(SkinItem.skinslink_count > 0)
    if keep is not None:
        stmt = stmt.where(SkinItem.id.not_in(keep))
    result = await db.execute(
        stmt.values(
            skinslink_min_units=None,
            skinslink_count=0,
            active=(SkinItem.count_auto > 0) | (SkinItem.lisskins_count > 0),
        ).execution_options(synchronize_session=False)
    )
    return _rowcount(result)


async def rollup(db: AsyncSession, *, settings: Settings, now: datetime) -> int:
    """Write the roll-up; returns the items whose Skinslink stock it set. Never commits."""
    if not settings.skinslink_active or not await mirror_fresh(db, settings=settings, now=now):
        await _clear(db)
        return 0
    agg = (
        select(
            SkinslinkItem.skin_item_id.label("item_id"),
            func.min(SkinslinkItem.price_units).label("min_units"),
            func.count().label("count"),
        )
        .where(SkinslinkItem.skin_item_id.is_not(None))
        .group_by(SkinslinkItem.skin_item_id)
        .subquery()
    )
    result = await db.execute(
        update(SkinItem)
        .where(SkinItem.id == agg.c.item_id)
        .values(skinslink_min_units=agg.c.min_units, skinslink_count=agg.c.count, active=True)
        .execution_options(synchronize_session=False)
    )
    await _clear(db, keep=select(agg.c.item_id))
    return _rowcount(result)


__all__ = ["rollup"]
