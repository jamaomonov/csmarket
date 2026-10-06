"""Prices come from the cheaper source; a stale or disabled mirror prices nothing."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from csmarket.core.clock import now
from csmarket.core.config import get_settings
from csmarket.core.redis import get_redis
from csmarket.modules.skins.models import SkinItem
from csmarket.modules.skins.prices import sync_skinslink_prices
from csmarket.modules.skins.repricing import reprice_rows
from csmarket.modules.skins.settings import load_rules
from csmarket.modules.skinslink.models import SkinslinkItem, SkinslinkState
from csmarket.modules.skinslink.rollup import rollup
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from tests.integration.orders_factory import make_item_and_rate

NOW = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)
ACTIVE = {"skinslink_enabled": True, "skinslink_api_key": "k", "skinslink_secret": "s"}


async def _waxpeer_item(db: AsyncSession, *, units: int | None = 12_345) -> SkinItem:
    item, _ = await make_item_and_rate(db)
    item.min_auto_units = units
    item.count_auto = 5 if units else 0
    item.active = units is not None
    await db.commit()
    return item


async def _mirror(
    db: AsyncSession, item: SkinItem, prices: list[int], synced: datetime = NOW
) -> None:
    db.add_all(
        [
            SkinslinkItem(
                id=f"9{i}",
                market_hash_name=item.market_hash_name,
                phase=item.phase,
                price_units=p,
                skin_item_id=item.id,
            )
            for i, p in enumerate(prices)
        ]
    )
    db.add(SkinslinkState(id=1, mirror_synced_at=synced, cursor="c"))
    await db.commit()


async def _reprice(db: AsyncSession, item: SkinItem) -> None:
    await reprice_rows(db, await load_rules(db))
    await db.commit()
    await db.refresh(item)


async def test_the_cheaper_source_prices_the_item(db_session: AsyncSession) -> None:
    item = await _waxpeer_item(db_session)
    await _reprice(db_session, item)
    waxpeer_only = item.sell_price_usd
    await _mirror(db_session, item, [11_000, 15_000])
    settings = get_settings().model_copy(update=ACTIVE)
    assert await rollup(db_session, settings=settings, now=NOW) == 1
    await db_session.commit()
    await _reprice(db_session, item)
    assert (item.skinslink_min_units, item.skinslink_count) == (11_000, 2)
    assert waxpeer_only is not None
    assert item.sell_price_usd is not None
    assert item.sell_price_usd < waxpeer_only


async def test_a_skinslink_only_item_becomes_active(db_session: AsyncSession) -> None:
    item = await _waxpeer_item(db_session, units=None)
    await _mirror(db_session, item, [5_000])
    await rollup(db_session, settings=get_settings().model_copy(update=ACTIVE), now=NOW)
    await db_session.commit()
    await _reprice(db_session, item)
    assert item.active is True
    assert item.sell_price_usd is not None


async def test_stale_mirror_does_not_price(db_session: AsyncSession) -> None:
    item = await _waxpeer_item(db_session)
    await _mirror(db_session, item, [1_000], synced=NOW - timedelta(minutes=11))
    await rollup(db_session, settings=get_settings().model_copy(update=ACTIVE), now=NOW)
    await db_session.commit()
    await db_session.refresh(item)
    # Waxpeer stock keeps the item on sale.
    assert (item.skinslink_min_units, item.skinslink_count, item.active) == (None, 0, True)


async def test_disabling_clears_an_earlier_rollup(db_session: AsyncSession) -> None:
    item = await _waxpeer_item(db_session, units=None)
    await _mirror(db_session, item, [1_000])
    await rollup(db_session, settings=get_settings().model_copy(update=ACTIVE), now=NOW)
    await rollup(db_session, settings=get_settings(), now=NOW)
    await db_session.commit()
    await db_session.refresh(item)
    assert (item.skinslink_min_units, item.skinslink_count, item.active) == (None, 0, False)


async def test_stock_that_left_the_mirror_is_cleared(db_session: AsyncSession) -> None:
    item = await _waxpeer_item(db_session)
    await _mirror(db_session, item, [1_000])
    settings = get_settings().model_copy(update=ACTIVE)
    await rollup(db_session, settings=settings, now=NOW)
    await db_session.execute(delete(SkinslinkItem))
    await rollup(db_session, settings=settings, now=NOW)
    await db_session.commit()
    await db_session.refresh(item)
    assert (item.skinslink_min_units, item.skinslink_count, item.active) == (None, 0, True)


async def test_skinslink_prices_without_any_waxpeer_tick(
    db_session: AsyncSession, db_engine: AsyncEngine
) -> None:
    """Prod may run Skinslink with no Waxpeer key: its own tick prices and lists the item,
    and a mirror gone stale takes it off sale again."""
    settings = get_settings().model_copy(update=ACTIVE)
    item = await _waxpeer_item(db_session, units=None)
    await _mirror(db_session, item, [9_000], synced=now())
    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    assert await sync_skinslink_prices(factory, get_redis(), settings=settings, at=now())
    await db_session.refresh(item)
    assert (item.active, item.skinslink_min_units) == (True, 9_000)
    assert item.sell_price_usd is not None
    later = now() + timedelta(minutes=settings.skinslink_mirror_stale_minutes + 1)
    assert await sync_skinslink_prices(factory, get_redis(), settings=settings, at=later)
    await db_session.refresh(item)
    assert (item.active, item.skinslink_count) == (False, 0)
    assert item.sell_price_usd is None  # type: ignore[unreachable]  # refreshed from the row


async def test_the_skinslink_tick_is_a_no_op_when_it_is_off_and_nothing_is_rolled_up(
    db_session: AsyncSession, db_engine: AsyncEngine
) -> None:
    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    assert not await sync_skinslink_prices(factory, get_redis(), settings=get_settings(), at=now())
