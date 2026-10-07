"""The non-Waxpeer sources on the catalogue (specs 2026-10-06, 2026-10-07).

:func:`sync_lisskins` — the ``lisskins.snapshot`` job: stream LIS-SKINS' export with no
transaction open (it takes minutes), then in one transaction under the pricing lock write
the snapshot, roll it up and reprice. :func:`sync_source_prices` — the ``sources.prices``
job (was ``skinslink.prices``): roll Skinslink and LIS-SKINS up and reprice without waiting
for a Waxpeer tick, so their prices appear — and leave when a source goes stale or is
switched off — on their own.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from redis.asyncio import Redis
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from csmarket.core import clock
from csmarket.core.config import Settings
from csmarket.core.logging import get_logger
from csmarket.modules.lisskins.api import (
    Collector,
    ExportReader,
    SnapshotResult,
    apply_snapshot,
    load_index,
    read_export,
)
from csmarket.modules.lisskins.api import rollup as lisskins_rollup
from csmarket.modules.skins.cachekeys import bump_catalog_version
from csmarket.modules.skins.models import SkinItem
from csmarket.modules.skins.repricing import lock_pricing, reprice_rows
from csmarket.modules.skins.settings import load_rules
from csmarket.modules.skinslink.api import rollup as skinslink_rollup

log = get_logger("csmarket.skins.source_prices")


async def sync_lisskins(
    session_factory: async_sessionmaker[AsyncSession],
    redis: Redis,
    *,
    settings: Settings,
    reader: ExportReader = read_export,
    now: Callable[[], datetime] = clock.now,
) -> SnapshotResult:
    """One snapshot tick (see the module docstring).

    Raises:
        LisskinsUnavailableError: The export could not be read whole — nothing is written.
    """
    async with session_factory() as db:
        index = await load_index(db)
        await db.commit()
    collected = Collector(index)
    last_update = await reader(
        settings.lisskins_export_url,
        collected.add,
        timeout_seconds=settings.lisskins_request_timeout_seconds,
    )
    at = now()
    async with session_factory() as db:
        await lock_pricing(db)
        result = await apply_snapshot(
            db, collected, snapshot_at=datetime.fromtimestamp(last_update, UTC), now=at
        )
        if result.refused:
            await db.rollback()
            return result
        await lisskins_rollup(db, settings=settings, now=at)
        await reprice_rows(db, await load_rules(db, fresh=True))
        await db.commit()
    await bump_catalog_version(redis)
    log.info(
        "lisskins.snapshot.applied",
        lots=result.lots,
        unmapped=result.unmapped,
        items=result.items,
        written=result.written,
        removed=result.removed,
    )
    return result


async def _clear_waxpeer_stock(db: AsyncSession) -> None:
    """Waxpeer buying is off: forget the stock an earlier Waxpeer tick wrote."""
    await db.execute(
        update(SkinItem)
        .where(SkinItem.count_auto > 0)
        .values(min_auto_units=None, count_auto=0, cheapest_auto=[], price_hash=None)
        .execution_options(synchronize_session=False)
    )


async def sync_source_prices(
    session_factory: async_sessionmaker[AsyncSession],
    redis: Redis,
    *,
    settings: Settings,
    at: datetime,
) -> bool:
    """Roll Skinslink and LIS-SKINS up and reprice; runs while either is on, or while an
    earlier roll-up of either is still on the catalogue to clear.

    Returns:
        Whether it repriced.
    """
    async with session_factory() as db:
        if not (settings.skinslink_active or settings.lisskins_active):
            left = await db.scalar(
                select(SkinItem.id)
                .where((SkinItem.skinslink_count > 0) | (SkinItem.lisskins_count > 0))
                .limit(1)
            )
            if left is None:
                return False
        await lock_pricing(db)
        if not settings.waxpeer_buy_enabled:
            await _clear_waxpeer_stock(db)
        await skinslink_rollup(db, settings=settings, now=at)
        await lisskins_rollup(db, settings=settings, now=at)
        await reprice_rows(db, await load_rules(db, fresh=True))
        await db.commit()
    await bump_catalog_version(redis)
    return True


__all__ = ["sync_lisskins", "sync_source_prices"]
