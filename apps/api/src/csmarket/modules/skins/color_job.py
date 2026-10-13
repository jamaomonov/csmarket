"""The ``skins.colors`` job's work: read the colours of pictures not read yet (spec 2026-10-14).

Wears of one skin share one ByMykel picture, so the work is per distinct ``image_url``: the
pictures whose rows have no colours for that picture yet (``colors_image`` ≠ ``image_url``)
and were not set by hand. Each is fetched small from the Steam CDN, read by
:func:`.colors.colors_of` and written to every row showing it. A network failure skips the
picture until the next tick; a picture that does not decode is marked read with no colours, so
it is not fetched forever. No DB connection is held across a fetch.
"""

from __future__ import annotations

import asyncio
import io
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import httpx
from PIL import Image, UnidentifiedImageError
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from csmarket.core.logging import get_logger
from csmarket.modules.skins.colors import SkinColor, colors_of
from csmarket.modules.skins.images import steam_image
from csmarket.modules.skins.models import SkinItem

log = get_logger("csmarket.skins.colors")

#: Pictures per tick: about 300 × 5-minute ticks reads the whole catalogue in a few hours.
BATCH = 300
#: Fetches in flight at once, gentle on the Steam CDN.
CONCURRENCY = 4
TIMEOUT_SECONDS = 6.0
#: Steam's economy images take a size suffix; this one is plenty for colours.
_SIZE_SUFFIX = "/128fx96f"

Fetch = Callable[[str], Awaitable[bytes | None]]


@dataclass(frozen=True)
class ColorRun:
    """What one tick did."""

    pictures: int
    read: int
    failed: int


def picture_url(url: str, *, host: str) -> str:
    """The small version of a picture on the configured Steam host."""
    out = steam_image(url, host=host) or url
    return out + _SIZE_SUFFIX if "/economy/image/" in out else out


async def _pending(db: AsyncSession, limit: int) -> list[str]:
    rows = await db.execute(
        select(SkinItem.image_url)
        .where(
            SkinItem.image_url.is_not(None),
            SkinItem.colors_manual.is_(False),
            SkinItem.colors_image.is_distinct_from(SkinItem.image_url),
        )
        .group_by(SkinItem.image_url)
        .limit(limit)
    )
    return [str(u) for u in rows.scalars().all()]


def read_colors(data: bytes) -> list[SkinColor]:
    """The colours of an encoded picture; ``[]`` when it does not decode."""
    try:
        with Image.open(io.BytesIO(data)) as img:
            return colors_of(img)
    except (UnidentifiedImageError, OSError, ValueError):
        return []


async def refresh_colors(
    factory: async_sessionmaker[AsyncSession],
    *,
    fetch: Fetch,
    host: str,
    limit: int = BATCH,
) -> ColorRun:
    """Read up to ``limit`` pictures and store their colours. Never raises on one picture."""
    async with factory() as db:
        urls = await _pending(db, limit)
    gate = asyncio.Semaphore(CONCURRENCY)

    async def one(url: str) -> tuple[str, bytes | None]:
        async with gate:
            return url, await fetch(picture_url(url, host=host))

    results = await asyncio.gather(*(one(u) for u in urls))
    read = failed = 0
    async with factory() as db:
        for url, data in results:
            if data is None:
                failed += 1
                continue
            await db.execute(
                update(SkinItem)
                .where(SkinItem.image_url == url, SkinItem.colors_manual.is_(False))
                .values(colors=read_colors(data), colors_image=url)
            )
            read += 1
        await db.commit()
    run = ColorRun(pictures=len(urls), read=read, failed=failed)
    log.info("skins.colors.done", pictures=run.pictures, read=run.read, failed=run.failed)
    return run


def http_fetch(client: httpx.AsyncClient) -> Fetch:
    """A :data:`Fetch` over ``client``: the body on 200, ``None`` on anything else."""

    async def fetch(url: str) -> bytes | None:
        try:
            response = await client.get(url, timeout=TIMEOUT_SECONDS)
        except httpx.HTTPError:
            return None
        return response.content if response.status_code == 200 else None

    return fetch


__all__ = [
    "BATCH",
    "ColorRun",
    "Fetch",
    "http_fetch",
    "picture_url",
    "read_colors",
    "refresh_colors",
]
