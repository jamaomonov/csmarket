"""The mirror of Skinslink's CS2 sale list (spec 2026-10-06 §3).

One full download (Available Items) on the first tick and after a ``reset``; then only the
changes (Catalogue Events) from the stored cursor, every 15 s. Items map to our catalogue by
``(market_hash_name, phase)`` — the same rule as Waxpeer's names (``skins.canonical_name``);
an item we do not sell is kept with ``skin_item_id NULL`` and never offered or priced.

A mirror older than ``skinslink_mirror_stale_minutes`` is not used (:func:`mirror_fresh`).
Re-applying an event is safe: upserts replace by id, a remove of a missing id removes nothing.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal, Protocol

from sqlalchemy import delete, select, tuple_
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.config import Settings
from csmarket.core.logging import get_logger
from csmarket.modules.skins.api import SkinItem, canonical_name
from csmarket.modules.skinslink.client import AvailablePage, CatalogueItem, EventsPage
from csmarket.modules.skinslink.models import SkinslinkItem, SkinslinkState

log = get_logger("csmarket.skinslink.mirror")

#: Rows per bulk statement (asyncpg caps bind parameters at 32 767).
_BATCH = 1000
#: Event pages one tick may follow before leaving the rest to the next tick.
MAX_PAGES_PER_TICK = 20
_UNIT = Decimal(1)
_FLOAT_PLACES = Decimal("0.000001")


class CatalogueClient(Protocol):
    """What the mirror needs from Skinslink."""

    async def available(self, game: str = "csgo") -> AvailablePage:
        """The whole sale list."""
        ...

    async def events(self, since: str, *, game: str = "csgo", limit: int = 10000) -> EventsPage:
        """Changes after ``since``."""
        ...


@dataclass(frozen=True)
class MirrorResult:
    """What one tick did."""

    mode: Literal["full", "events", "reset"]
    upserts: int
    removes: int
    pages: int


def to_units(price_usd: Decimal) -> int:
    """USD as units (1000 = $1), half up — the catalogue's cost unit."""
    return int((price_usd * 1000).quantize(_UNIT, rounding=ROUND_HALF_UP))


def split_phase(name: str, phase: str | None) -> tuple[str, str]:
    """Our ``(market_hash_name, phase)`` for a Skinslink name and its ``phase`` field.

    A phase written into the name (Waxpeer's habit) is moved out as for Waxpeer; the
    ``phase`` field wins when both are present.
    """
    base, inline = canonical_name(name)
    return base, phase or inline


async def _keys_to_items(
    db: AsyncSession, keys: Iterable[tuple[str, str]]
) -> dict[tuple[str, str], str]:
    """Our ``skin_items.id`` for each ``(market_hash_name, phase)`` we sell."""
    wanted = list(set(keys))
    found: dict[tuple[str, str], str] = {}
    for start in range(0, len(wanted), _BATCH):
        chunk = wanted[start : start + _BATCH]
        rows = await db.execute(
            select(SkinItem.id, SkinItem.market_hash_name, SkinItem.phase).where(
                tuple_(SkinItem.market_hash_name, SkinItem.phase).in_(chunk)
            )
        )
        found.update({(name, phase): item_id for item_id, name, phase in rows.all()})
    return found


async def _upsert(db: AsyncSession, items: Sequence[CatalogueItem], *, now: datetime) -> int:
    """Insert or replace ``items`` by id; returns how many."""
    keyed = [(i, split_phase(i.name, i.phase)) for i in items]
    ids = await _keys_to_items(db, (key for _, key in keyed))
    rows = [
        {
            "id": i.id,
            "market_hash_name": name,
            "phase": phase,
            "price_units": to_units(i.price_usd),
            "float_value": None
            if i.float_value is None
            else Decimal(str(i.float_value)).quantize(_FLOAT_PLACES),
            "paint_seed": i.paint_seed,
            "inspect_url": i.inspect_url,
            "image_url": i.image_url,
            "skin_item_id": ids.get((name, phase)),
            "updated_at": now,
        }
        for i, (name, phase) in keyed
    ]
    for start in range(0, len(rows), _BATCH):
        stmt = pg_insert(SkinslinkItem).values(rows[start : start + _BATCH])
        await db.execute(
            stmt.on_conflict_do_update(
                index_elements=[SkinslinkItem.id],
                set_={
                    col: stmt.excluded[col]
                    for col in (
                        "market_hash_name",
                        "phase",
                        "price_units",
                        "float_value",
                        "paint_seed",
                        "inspect_url",
                        "image_url",
                        "skin_item_id",
                        "updated_at",
                    )
                },
            )
        )
    return len(rows)


async def _remove(db: AsyncSession, ids: Sequence[str]) -> int:
    for start in range(0, len(ids), _BATCH):
        await db.execute(
            delete(SkinslinkItem).where(SkinslinkItem.id.in_(ids[start : start + _BATCH]))
        )
    return len(ids)


async def _touch(db: AsyncSession, *, cursor: str, now: datetime, full: bool = False) -> None:
    """Store the cursor and the sync time on row 1."""
    state = await db.get(SkinslinkState, 1) or SkinslinkState(id=1)
    state.cursor = cursor
    state.mirror_synced_at = now
    if full:
        state.full_loaded_at = now
    db.add(state)


async def _full(
    factory: Callable[[], AsyncSession],
    client: CatalogueClient,
    *,
    now: datetime,
    mode: Literal["full", "reset"],
) -> MirrorResult:
    page = await client.available()
    async with factory() as db:
        await db.execute(delete(SkinslinkItem))
        upserts = await _upsert(db, page.items, now=now)
        await _touch(db, cursor=page.last_update_at, now=now, full=True)
        await db.commit()
    log.info("skinslink.mirror.loaded", mode=mode, items=upserts)
    return MirrorResult(mode=mode, upserts=upserts, removes=0, pages=1)


async def sync_mirror(
    factory: Callable[[], AsyncSession], client: CatalogueClient, *, now: datetime
) -> MirrorResult:
    """One tick: a full load without a cursor (or on ``reset``), else the events since it.

    Each events page is applied and its ``next`` stored in one transaction, so a crash
    mid-tick resumes from the last page applied. Errors from ``client`` propagate (the job
    logs them; the mirror keeps its last good state).
    """
    async with factory() as db:
        cursor = await db.scalar(select(SkinslinkState.cursor).where(SkinslinkState.id == 1))
    if cursor is None:
        return await _full(factory, client, now=now, mode="full")
    pages = upserts = removes = 0
    since = cursor
    while pages < MAX_PAGES_PER_TICK:
        page = await client.events(since)
        pages += 1
        if page.reset:
            return await _full(factory, client, now=now, mode="reset")
        async with factory() as db:
            upserts += await _upsert(
                db, [e.item for e in page.events if e.type == "upsert" and e.item], now=now
            )
            removes += await _remove(db, [e.id for e in page.events if e.type == "remove"])
            await _touch(db, cursor=page.next, now=now)
            await db.commit()
        since = page.next
        if not page.more:
            break
    return MirrorResult(mode="events", upserts=upserts, removes=removes, pages=pages)


async def mirror_fresh(db: AsyncSession, *, settings: Settings, now: datetime) -> bool:
    """The mirror was synced within ``skinslink_mirror_stale_minutes``."""
    synced = await db.scalar(select(SkinslinkState.mirror_synced_at).where(SkinslinkState.id == 1))
    return synced is not None and now - synced <= timedelta(
        minutes=settings.skinslink_mirror_stale_minutes
    )


__all__ = [
    "MAX_PAGES_PER_TICK",
    "CatalogueClient",
    "MirrorResult",
    "mirror_fresh",
    "split_phase",
    "sync_mirror",
    "to_units",
]
