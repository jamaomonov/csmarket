"""LIS-SKINS on the catalogue, kept honest every price tick (spec 2026-10-07 §4).

The snapshot writes ``lisskins_min_units`` / ``lisskins_count``. Each price tick then: while
LIS-SKINS is on and its snapshot fresh, an item with LIS-SKINS lots is on sale (a Waxpeer
tick may have switched it off); otherwise every LIS-SKINS roll-up is cleared and ``active``
re-derived from the other sources. ``skins.repricing`` then prices from the cheapest side.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.config import Settings
from csmarket.modules.lisskins.snapshot import snapshot_fresh
from csmarket.modules.skins.api import SkinItem


def _rowcount(result: object) -> int:
    """``rowcount`` lives on CursorResult; async ``execute`` is typed as Result."""
    return int(getattr(result, "rowcount", 0) or 0)


async def rollup(db: AsyncSession, *, settings: Settings, now: datetime) -> int:
    """Apply the rule above; returns the rows it changed. Never commits."""
    stmt = update(SkinItem).where(SkinItem.lisskins_count > 0)
    if settings.lisskins_active and await snapshot_fresh(db, settings=settings, now=now):
        stmt = stmt.where(SkinItem.active.is_(False)).values(active=True)
    else:
        stmt = stmt.values(
            lisskins_min_units=None,
            lisskins_count=0,
            active=(SkinItem.count_auto > 0) | (SkinItem.skinslink_count > 0),
        )
    result = await db.execute(stmt.execution_options(synchronize_session=False))
    return _rowcount(result)


__all__ = ["rollup"]
