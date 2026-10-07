"""LIS-SKINS on the catalogue: cleared when off or stale (an item only it stocked goes off
sale), back on sale after a Waxpeer tick, and the sources' tick."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from csmarket.core.config import get_settings
from csmarket.core.redis import get_redis
from csmarket.modules.lisskins.api import rollup
from csmarket.modules.lisskins.models import LisskinsState
from csmarket.modules.skins.models import SkinItem
from csmarket.modules.skins.prices import apply_prices
from csmarket.modules.skins.source_prices import sync_source_prices
from csmarket.modules.skinslink.api import rollup as skinslink_rollup
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from tests.integration.orders_factory import make_item_and_rate

NOW = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)
ON = get_settings().model_copy(update={"lisskins_enabled": True, "lisskins_api_key": "k"})


async def _stocked(db: AsyncSession, *, waxpeer: int = 0, snapshot_age_minutes: int = 1) -> str:
    item, _ = await make_item_and_rate(db)
    item.lisskins_min_units, item.lisskins_count = 11_000, 4
    item.count_auto, item.min_auto_units = waxpeer, (12_000 if waxpeer else None)
    item.active = True
    await db.merge(
        LisskinsState(id=1, snapshot_at=NOW - timedelta(minutes=snapshot_age_minutes), lots=4)
    )
    await db.commit()
    return item.id


async def _row(db: AsyncSession, item_id: str) -> SkinItem:
    row = await db.get(SkinItem, item_id, populate_existing=True)
    assert row is not None
    return row


async def test_a_stale_snapshot_clears_and_takes_a_lisskins_only_item_off_sale(
    db_session: AsyncSession,
) -> None:
    only = await _stocked(db_session, snapshot_age_minutes=21)
    both = await _stocked(db_session, waxpeer=3, snapshot_age_minutes=21)
    await rollup(db_session, settings=ON, now=NOW)
    await db_session.commit()
    a, b = await _row(db_session, only), await _row(db_session, both)
    assert (a.lisskins_min_units, a.lisskins_count, a.active) == (None, 0, False)
    assert (b.lisskins_count, b.active) == (0, True)


async def test_switched_off_clears(db_session: AsyncSession) -> None:
    item_id = await _stocked(db_session)
    await rollup(db_session, settings=get_settings(), now=NOW)
    await db_session.commit()
    assert (await _row(db_session, item_id)).lisskins_count == 0


async def test_a_waxpeer_tick_and_the_skinslink_clear_keep_a_lisskins_item_on_sale(
    db_session: AsyncSession,
) -> None:
    item_id = await _stocked(db_session)
    row = await _row(db_session, item_id)
    row.skinslink_min_units, row.skinslink_count = 12_000, 1  # Skinslink stock, then cleared
    await db_session.commit()
    await apply_prices(db_session, {}, meta=[], at=NOW)  # Waxpeer lists nothing for it
    await skinslink_rollup(db_session, settings=get_settings(), now=NOW)  # Skinslink off
    await db_session.commit()
    assert (await _row(db_session, item_id)).active is True


async def test_a_fresh_snapshot_puts_a_switched_off_item_back_on_sale(
    db_session: AsyncSession,
) -> None:
    item_id = await _stocked(db_session)
    row = await _row(db_session, item_id)
    row.active = False
    await db_session.commit()
    assert await rollup(db_session, settings=ON, now=NOW) == 1
    await db_session.commit()
    assert (await _row(db_session, item_id)).active is True


async def test_the_sources_tick_runs_only_with_a_source_on_or_something_to_clear(
    db_session: AsyncSession, db_engine: AsyncEngine
) -> None:
    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    off = get_settings()
    assert await sync_source_prices(factory, get_redis(), settings=off, at=NOW) is False
    item_id = await _stocked(db_session)
    assert await sync_source_prices(factory, get_redis(), settings=off, at=NOW) is True
    assert (await _row(db_session, item_id)).lisskins_count == 0
    assert await sync_source_prices(factory, get_redis(), settings=ON, at=NOW) is True
