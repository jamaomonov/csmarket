"""The snapshot of LIS-SKINS' instant lots (spec 2026-10-07 §3).

:func:`load_index` maps a lot's name to our catalogue as the Skinslink mirror does
(``skins.canonical_name``), plus one rule of its own: a Doppler-family name without a phase
is placed by ``item_paint_index`` against ``skin_items.paint_index`` (each phase is its own
paint). :class:`Collector` is fed every sellable lot of the export and keeps, per catalogue
item, how many there are and the :data:`KEEP` cheapest; unmapped names are counted and
dropped, so memory stays at ~10 lots per item whatever the export's size.
:func:`apply_snapshot` writes it in the caller's transaction: the offers that changed, the
ones that left, the roll-up onto ``skin_items`` and ``lisskins_state`` — or nothing, when the
export holds under :data:`MIN_SHARE` of the previous tick's lots.
"""

from __future__ import annotations

import heapq
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.config import Settings
from csmarket.core.logging import get_logger
from csmarket.modules.lisskins.export import Lot
from csmarket.modules.lisskins.models import LisskinsOffer, LisskinsState
from csmarket.modules.skins.api import SkinItem, canonical_name

log = get_logger("csmarket.lisskins.snapshot")

#: Lots kept per catalogue item.
KEEP = 10
#: A tick whose export has fewer sellable lots than this share of the last applied one is
#: refused (a cut or broken export must not read as a sold-out market).
MIN_SHARE = 0.5
#: Rows per bulk statement (asyncpg caps bind parameters at 32 767).
_BATCH = 1000
_COLUMNS = (
    "skin_item_id",
    "price_units",
    "float_value",
    "paint_seed",
    "asset_id",
    "inspect_url",
    "stickers",
    "updated_at",
)


class CatalogueIndex:
    """Our ``skin_items.id`` for a LIS-SKINS name (and paint index)."""

    def __init__(self, rows: Iterable[tuple[str, str, str, int | None]]) -> None:
        self._plain: dict[tuple[str, str], str] = {}
        self._painted: dict[tuple[str, int], str] = {}
        self._seen: dict[tuple[str, int | None], str | None] = {}
        for item_id, name, phase, paint in rows:
            self._plain[(name, phase)] = item_id
            if phase and paint is not None:
                self._painted[(name, paint)] = item_id

    def item_for(self, name: str, paint_index: int | None) -> str | None:
        """The catalogue item, or ``None`` when we do not sell it (memoised per name)."""
        key = (name, paint_index)
        if key not in self._seen:
            self._seen[key] = self._lookup(name, paint_index)
        return self._seen[key]

    def _lookup(self, name: str, paint_index: int | None) -> str | None:
        base, inline = canonical_name(name)
        if inline:
            return self._plain.get((base, inline))
        if paint_index is not None and (hit := self._painted.get((base, paint_index))):
            return hit
        return self._plain.get((base, ""))


async def load_index(db: AsyncSession) -> CatalogueIndex:
    """Every catalogue row's name, phase and paint index."""
    rows = await db.execute(
        select(SkinItem.id, SkinItem.market_hash_name, SkinItem.phase, SkinItem.paint_index)
    )
    return CatalogueIndex((r[0], r[1], r[2], r[3]) for r in rows.all())


@dataclass
class _Kept:
    """One item's lots: how many, and a heap of the cheapest (dearest at the root)."""

    count: int = 0
    #: ``(-price, -lot id, -arrival, lot)``: the root is the one to drop next.
    heap: list[tuple[int, int, int, Lot]] = field(default_factory=list)


class Collector:
    """Fed every sellable lot of one export; keeps what the snapshot writes."""

    def __init__(self, index: CatalogueIndex, *, keep: int = KEEP) -> None:
        self._index = index
        self._keep = keep
        self.lots = 0
        self.unmapped = 0
        self.items: dict[str, _Kept] = {}

    def add(self, lot: Lot) -> None:
        """Count ``lot`` and keep it if it is among its item's cheapest."""
        self.lots += 1
        item_id = self._index.item_for(lot.name, lot.paint_index)
        if item_id is None:
            self.unmapped += 1
            return
        kept = self.items.setdefault(item_id, _Kept())
        kept.count += 1
        entry = (-lot.price_units, -lot.id, -self.lots, lot)
        if len(kept.heap) < self._keep:
            heapq.heappush(kept.heap, entry)
        elif entry[:3] > kept.heap[0][:3]:
            heapq.heapreplace(kept.heap, entry)

    def cheapest(self, item_id: str) -> list[Lot]:
        """The item's kept lots, cheapest first (then by id)."""
        return [e[3] for e in sorted(self.items[item_id].heap, key=lambda e: e[:3], reverse=True)]

    def summary(self) -> dict[str, tuple[int, int]]:
        """``(cheapest units, lot count)`` per item."""
        return {
            item_id: (-max(e[0] for e in kept.heap), kept.count)
            for item_id, kept in self.items.items()
        }


@dataclass(frozen=True)
class SnapshotResult:
    """What one tick did."""

    refused: bool
    lots: int
    unmapped: int = 0
    items: int = 0
    written: int = 0
    removed: int = 0
    snapshot_at: datetime | None = None


# Any: one row of ``lisskins_offers`` for a bulk insert.
def _row(item_id: str, lot: Lot, now: datetime) -> dict[str, Any]:
    return {
        "id": lot.id,
        "skin_item_id": item_id,
        "price_units": lot.price_units,
        "float_value": lot.float_value,
        "paint_seed": lot.paint_seed,
        "asset_id": lot.asset_id,
        "inspect_url": lot.inspect_url,
        "stickers": [asdict(s) for s in lot.stickers],
        "updated_at": now,
    }


async def _write_offers(
    db: AsyncSession, collected: Collector, *, now: datetime
) -> tuple[int, int]:
    """Upsert the kept lots that are new or moved; delete the ones that left."""
    have = {
        r[0]: (r[1], r[2])
        for r in (
            await db.execute(
                select(LisskinsOffer.id, LisskinsOffer.price_units, LisskinsOffer.skin_item_id)
            )
        ).all()
    }
    # One statement may touch a row once: a lot id the export lists twice is written once.
    rows = list(
        {
            lot.id: _row(item_id, lot, now)
            for item_id in collected.items
            for lot in collected.cheapest(item_id)
        }.values()
    )
    changed = [r for r in rows if have.get(r["id"]) != (r["price_units"], r["skin_item_id"])]
    for start in range(0, len(changed), _BATCH):
        stmt = pg_insert(LisskinsOffer).values(changed[start : start + _BATCH])
        await db.execute(
            stmt.on_conflict_do_update(
                index_elements=[LisskinsOffer.id], set_={c: stmt.excluded[c] for c in _COLUMNS}
            )
        )
    gone = list(have.keys() - {r["id"] for r in rows})
    for start in range(0, len(gone), _BATCH):
        await db.execute(
            delete(LisskinsOffer).where(LisskinsOffer.id.in_(gone[start : start + _BATCH]))
        )
    return len(changed), len(gone)


async def _write_rollup(db: AsyncSession, collected: Collector) -> None:
    """``lisskins_min_units`` / ``lisskins_count`` for every item with lots; cleared (and
    ``active`` re-derived from the other sources) for those that have none now."""
    want = collected.summary()
    have = {
        r[0]: (r[1], r[2])
        for r in (
            await db.execute(
                select(SkinItem.id, SkinItem.lisskins_min_units, SkinItem.lisskins_count).where(
                    SkinItem.lisskins_count > 0
                )
            )
        ).all()
    }
    updates = [
        {"id": item_id, "lisskins_min_units": m, "lisskins_count": n, "active": True}
        for item_id, (m, n) in want.items()
        if have.get(item_id) != (m, n)
    ]
    for start in range(0, len(updates), _BATCH):
        await db.execute(update(SkinItem), updates[start : start + _BATCH])
    gone = list(have.keys() - want.keys())
    for start in range(0, len(gone), _BATCH):
        await db.execute(
            update(SkinItem)
            .where(SkinItem.id.in_(gone[start : start + _BATCH]))
            .values(
                lisskins_min_units=None,
                lisskins_count=0,
                active=(SkinItem.count_auto > 0) | (SkinItem.skinslink_count > 0),
            )
            .execution_options(synchronize_session=False)
        )


async def apply_snapshot(
    db: AsyncSession, collected: Collector, *, snapshot_at: datetime, now: datetime
) -> SnapshotResult:
    """Write the collected export (never commits); refused — nothing written — when it holds
    fewer than :data:`MIN_SHARE` of the previous tick's lots."""
    state = await db.get(LisskinsState, 1) or LisskinsState(id=1, lots=0)
    if state.lots and collected.lots < state.lots * MIN_SHARE:
        log.warning("lisskins.snapshot.refused", lots=collected.lots, before=state.lots)
        return SnapshotResult(refused=True, lots=collected.lots, snapshot_at=snapshot_at)
    written, removed = await _write_offers(db, collected, now=now)
    await _write_rollup(db, collected)
    state.snapshot_at, state.synced_at, state.lots = snapshot_at, now, collected.lots
    db.add(state)
    return SnapshotResult(
        refused=False,
        lots=collected.lots,
        unmapped=collected.unmapped,
        items=len(collected.items),
        written=written,
        removed=removed,
        snapshot_at=snapshot_at,
    )


async def snapshot_fresh(db: AsyncSession, *, settings: Settings, now: datetime) -> bool:
    """The applied export was made within ``lisskins_stale_minutes``."""
    made = await db.scalar(select(LisskinsState.snapshot_at).where(LisskinsState.id == 1))
    return made is not None and now - made <= timedelta(minutes=settings.lisskins_stale_minutes)


__all__ = [
    "KEEP",
    "MIN_SHARE",
    "CatalogueIndex",
    "Collector",
    "SnapshotResult",
    "apply_snapshot",
    "load_index",
    "snapshot_fresh",
]
