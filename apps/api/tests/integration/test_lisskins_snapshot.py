"""The LIS-SKINS snapshot: mapping (Dopplers by paint), the ten cheapest, changes and
deletes, the collapse rule, a cut export, and prices from the cheaper source."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from csmarket.core.config import get_settings
from csmarket.core.ids import new_id
from csmarket.core.redis import get_redis
from csmarket.modules.lisskins.api import (
    ExportReader,
    LisskinsUnavailableError,
    Lot,
    SnapshotResult,
    Sticker,
)
from csmarket.modules.lisskins.models import LisskinsOffer, LisskinsState
from csmarket.modules.skins.models import SkinItem
from csmarket.modules.skins.pricing import quote
from csmarket.modules.skins.settings import load_rules
from csmarket.modules.skins.source_prices import sync_lisskins
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from tests.integration.orders_factory import make_item_and_rate

LAST = 1_759_831_200
NOW = datetime.fromtimestamp(LAST, UTC) + timedelta(minutes=1)
SETTINGS = get_settings().model_copy(update={"lisskins_enabled": True, "lisskins_api_key": "k"})


def _lot(id_: int, name: str, units: int, *, paint: int | None = None) -> Lot:
    return Lot(
        id=id_,
        name=name,
        price_units=units,
        paint_index=paint,
        float_value=Decimal("0.25"),
        paint_seed=1,
        asset_id=str(38_000_000_000 + id_),
        inspect_url=None,
        stickers=(Sticker(name="Sticker | Crown (Foil)", image=None, slot=0, wear=None),),
    )


def _reader(*lots: Lot, fail_after: int | None = None) -> ExportReader:
    async def read(url: str, on_lot: Callable[[Lot], None], *, timeout_seconds: float) -> int:
        for n, lot in enumerate(lots):
            if n == fail_after:
                raise LisskinsUnavailableError("cut")
            on_lot(lot)
        return LAST

    return read


async def _sync(engine: AsyncEngine, *lots: Lot, fail_after: int | None = None) -> SnapshotResult:
    return await sync_lisskins(
        async_sessionmaker(bind=engine, expire_on_commit=False),
        get_redis(),
        settings=SETTINGS,
        reader=_reader(*lots, fail_after=fail_after),
        now=lambda: NOW,
    )


async def _offers(db: AsyncSession) -> dict[int, tuple[int, str]]:
    rows = (await db.scalars(select(LisskinsOffer).execution_options(populate_existing=True))).all()
    return {r.id: (r.price_units, r.skin_item_id) for r in rows}


async def _item(db: AsyncSession, item_id: str) -> SkinItem:
    row = await db.get(SkinItem, item_id, populate_existing=True)
    assert row is not None
    return row


async def test_lots_map_to_the_catalogue_and_the_ten_cheapest_are_kept(
    db_session: AsyncSession, db_engine: AsyncEngine
) -> None:
    item, _ = await make_item_and_rate(db_session)
    lots = [_lot(n, item.market_hash_name, 10_000 + n * 10) for n in range(12, 0, -1)]
    result = await _sync(db_engine, *lots, _lot(99, "Nope | Nothing (Field-Tested)", 1))
    assert (result.refused, result.lots, result.unmapped, result.items) == (False, 13, 1, 1)
    assert sorted(await _offers(db_session)) == list(range(1, 11))
    row = await _item(db_session, item.id)
    assert (row.lisskins_min_units, row.lisskins_count, row.active) == (10_010, 12, True)
    assert row.sell_price_usd is not None
    state = await db_session.get(LisskinsState, 1)
    assert state is not None
    assert (state.snapshot_at, state.synced_at, state.lots) == (
        datetime.fromtimestamp(LAST, UTC),
        NOW,
        13,
    )
    kept = await db_session.get(LisskinsOffer, 1)
    assert kept is not None
    assert kept.stickers == [
        {"name": "Sticker | Crown (Foil)", "image": None, "slot": 0, "wear": None}
    ]


async def test_a_doppler_without_a_phase_maps_by_paint_index(
    db_session: AsyncSession, db_engine: AsyncEngine
) -> None:
    name = "★ Karambit | Doppler (Factory New)"
    rows = [
        SkinItem(
            id=new_id(),
            market_hash_name=name,
            phase=phase,
            paint_index=paint,
            slug=f"karambit-doppler-fn-{paint}",
            category="knives",
            search_text="karambit doppler",
        )
        for phase, paint in (("Phase 2", 419), ("Phase 3", 420))
    ]
    db_session.add_all(rows)
    await db_session.commit()
    result = await _sync(
        db_engine, _lot(1, name, 500_000, paint=420), _lot(2, name, 400_000, paint=999)
    )
    assert await _offers(db_session) == {1: (500_000, rows[1].id)}
    assert result.unmapped == 1  # paint 999: no phase, no plain row
    assert (await _item(db_session, rows[0].id)).lisskins_count == 0


async def test_a_second_tick_writes_what_changed_and_deletes_what_left(
    db_session: AsyncSession, db_engine: AsyncEngine
) -> None:
    a, _ = await make_item_and_rate(db_session)
    b, _ = await make_item_and_rate(db_session)
    await _sync(
        db_engine,
        _lot(1, a.market_hash_name, 10_000),
        _lot(2, a.market_hash_name, 11_000),
        _lot(3, b.market_hash_name, 9_000),
    )
    await _sync(
        db_engine,
        _lot(2, a.market_hash_name, 10_500),
        _lot(4, a.market_hash_name, 12_000),
        _lot(5, a.market_hash_name, 12_500),
    )
    assert await _offers(db_session) == {
        2: (10_500, a.id),
        4: (12_000, a.id),
        5: (12_500, a.id),
    }
    row_a, row_b = await _item(db_session, a.id), await _item(db_session, b.id)
    assert (row_a.lisskins_min_units, row_a.lisskins_count) == (10_500, 3)
    assert (row_b.lisskins_min_units, row_b.lisskins_count, row_b.active) == (None, 0, False)


async def test_a_collapsed_export_is_refused(
    db_session: AsyncSession, db_engine: AsyncEngine
) -> None:
    item, _ = await make_item_and_rate(db_session)
    name = item.market_hash_name
    await _sync(db_engine, *[_lot(n, name, 10_000 + n) for n in range(1, 11)])
    result = await _sync(db_engine, *[_lot(n, name, 9_000) for n in range(1, 5)])
    assert result.refused is True
    assert len(await _offers(db_session)) == 10
    assert (await _item(db_session, item.id)).lisskins_count == 10


async def test_a_truncated_export_changes_nothing(
    db_session: AsyncSession, db_engine: AsyncEngine
) -> None:
    item, _ = await make_item_and_rate(db_session)
    name = item.market_hash_name
    await _sync(db_engine, _lot(1, name, 10_000), _lot(2, name, 11_000), _lot(3, name, 12_000))
    before = await _offers(db_session)
    with pytest.raises(LisskinsUnavailableError):
        await _sync(db_engine, _lot(1, name, 5_000), _lot(9, name, 5_000), fail_after=1)
    assert await _offers(db_session) == before
    row = await _item(db_session, item.id)
    assert (row.lisskins_min_units, row.lisskins_count) == (10_000, 3)


async def test_the_cheaper_source_prices_the_card(
    db_session: AsyncSession, db_engine: AsyncEngine
) -> None:
    item, _ = await make_item_and_rate(db_session)
    item.skinslink_min_units, item.skinslink_count, item.active = 12_000, 1, True
    await db_session.commit()
    await _sync(db_engine, _lot(1, item.market_hash_name, 11_000))
    row = await _item(db_session, item.id)
    expected = quote(
        11_000,
        rules=await load_rules(db_session, fresh=True),
        category=row.category,
        weapon=row.weapon,
        count_auto=row.stock_count,
        item_pp=row.margin_override_pp,
        fixed_price_usd=row.fixed_price_usd,
        steam_price_units=row.steam_price_units,
    ).price_usd
    assert row.sell_price_usd == expected
