"""Catalogue pictures by market name, for modules that only know a name (``desk``)."""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.modules.skins.models import SkinItem


async def images_by_name(db: AsyncSession, names: Iterable[str]) -> dict[str, str]:
    """Our catalogue's picture for each of ``names`` that has one, as stored.

    The phase is ignored: the first match wins, an item without a phase first. Names with no
    picture are left out. Hidden items count — a picture is not a listing.
    """
    wanted = sorted({n for n in names if n})
    if not wanted:
        return {}
    rows = await db.execute(
        select(SkinItem.market_hash_name, SkinItem.image_url)
        .where(SkinItem.market_hash_name.in_(wanted), SkinItem.image_url.is_not(None))
        .order_by(SkinItem.market_hash_name, SkinItem.phase != "", SkinItem.id)
    )
    found: dict[str, str] = {}
    for name, url in rows.all():
        if url:
            found.setdefault(name, url)
    return found


__all__ = ["images_by_name"]
