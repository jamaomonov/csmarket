"""Names and images of the stickers and charms an inspect link names by ``def_index``.

They come from our own catalogue: the ByMykel import writes ``def_index`` on its ``stickers``
and ``keychains`` rows (categories ``stickers`` / ``charms``). One indexed query per call.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Literal

from sqlalchemy import select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.modules.skins.models import SkinItem

#: What is applied to an item, as the catalogue's category names it.
Kind = Literal["stickers", "charms"]


async def applied_cards(
    db: AsyncSession, refs: Iterable[tuple[Kind, int]]
) -> dict[tuple[Kind, int], tuple[str, str | None]]:
    """``(kind, def_index) → (name, image_url)`` for every ref the catalogue knows."""
    wanted = list(set(refs))
    if not wanted:
        return {}
    rows = await db.execute(
        select(
            SkinItem.category, SkinItem.def_index, SkinItem.market_hash_name, SkinItem.image_url
        ).where(tuple_(SkinItem.category, SkinItem.def_index).in_(wanted))
    )
    found: dict[tuple[Kind, int], tuple[str, str | None]] = {}
    for category, def_index, name, image in rows.all():
        if category in ("stickers", "charms") and def_index is not None:
            kind: Kind = "stickers" if category == "stickers" else "charms"
            found[(kind, def_index)] = (name, image)
    return found


__all__ = ["Kind", "applied_cards"]
