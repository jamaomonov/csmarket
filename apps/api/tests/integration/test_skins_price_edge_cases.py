"""Import and price-tick edge cases, on shapes taken from real ByMykel and Waxpeer data."""

from __future__ import annotations

import fakeredis.aioredis
import pytest
from csmarket.core.clock import now
from csmarket.modules.skins.bymykel import dedupe, rows_from_file, rows_from_skins, upsert_items
from csmarket.modules.skins.cachekeys import catalog_version
from csmarket.modules.skins.models import SkinItem
from csmarket.modules.skins.prices import aggregate, apply_prices, sync_prices
from csmarket.modules.skins.waxpeer import SnapshotRow
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

pytestmark = pytest.mark.asyncio


def _skin(name: str, **extra: object) -> dict[str, object]:
    return {
        "market_hash_name": name,
        "category": {"name": "Pistols"},
        "stattrak": False,
        "souvenir": False,
        **extra,
    }


async def _slugs(db: AsyncSession) -> dict[str, str]:
    db.expire_all()
    rows = (await db.execute(select(SkinItem.market_hash_name, SkinItem.slug))).all()
    return {name: slug for name, slug in rows}


async def test_names_that_fold_to_one_slug_both_import(db_session: AsyncSession) -> None:
    rows = dedupe(
        rows_from_skins(
            [
                _skin("Desert Eagle | Sunset Storm 壱 (Field-Tested)"),
                _skin("Desert Eagle | Sunset Storm 弐 (Field-Tested)"),
            ]
        )
        + rows_from_file(
            "stickers",
            [
                {"market_hash_name": "Sticker | NiKo | London 2018"},
                {"market_hash_name": "Sticker | niko  | London 2018"},
            ],
        )
    )
    await upsert_items(db_session, rows)
    await db_session.commit()
    slugs = await _slugs(db_session)
    assert len(slugs) == 4
    assert len(set(slugs.values())) == 4
    # A second import keeps every slug where it was.
    await upsert_items(db_session, rows)
    await db_session.commit()
    assert await _slugs(db_session) == slugs


async def test_stub_slug_collision_does_not_abort_the_tick(db_session: AsyncSession) -> None:
    await upsert_items(
        db_session,
        rows_from_file("stickers", [{"market_hash_name": "Sticker | NiKo | London 2018"}]),
    )
    await db_session.commit()
    snapshot = [SnapshotRow(1, "Sticker | niko  | London 2018", 500, True)]
    result = await apply_prices(db_session, aggregate(snapshot), meta=[], at=now())
    await db_session.commit()
    assert result.stubs == 1
    slugs = await _slugs(db_session)
    assert len(set(slugs.values())) == 2


async def test_a_value_that_appears_later_is_written(db_session: AsyncSession) -> None:
    await upsert_items(db_session, rows_from_skins([_skin("P250 | Sand Dune (Field-Tested)")]))
    await db_session.commit()
    later = rows_from_skins(
        [
            _skin(
                "P250 | Sand Dune (Field-Tested)",
                image="https://community.akamai.steamstatic.com/x",
            )
        ]
    )
    assert await upsert_items(db_session, later) == 1
    await db_session.commit()
    db_session.expire_all()
    row = (await db_session.execute(select(SkinItem))).scalar_one()
    assert row.image_url == "https://community.akamai.steamstatic.com/x"


async def test_phaseless_doppler_stub_stays_hidden(db_session: AsyncSession) -> None:
    snapshot = [SnapshotRow(1, "★ Karambit | Doppler (Factory New)", 900000, True)]
    for _ in range(2):  # the stub tick, then an update tick
        await apply_prices(db_session, aggregate(snapshot), meta=[], at=now())
        await db_session.commit()
        snapshot = [SnapshotRow(1, "★ Karambit | Doppler (Factory New)", 890000, True)]
    db_session.expire_all()
    row = (await db_session.execute(select(SkinItem))).scalar_one()
    assert (row.phase, row.active, row.count_auto) == ("", False, 1)


async def test_zero_steam_price_is_stored_as_unknown(db_session: AsyncSession) -> None:
    snapshot = [SnapshotRow(1, "AK-47 | Redline (Field-Tested)", 27867, True)]
    meta = [{"name": "AK-47 | Redline (Field-Tested)", "steam_price": 0, "type": "Rifles"}]
    await apply_prices(db_session, aggregate(snapshot), meta=meta, at=now())
    await db_session.commit()
    db_session.expire_all()
    assert (await db_session.execute(select(SkinItem))).scalar_one().steam_price_units is None


class _Client:
    def __init__(self, rows: list[SnapshotRow]) -> None:
        self.rows = rows

    async def iter_snapshot_rows(self, *, game: str = "csgo"):  # type: ignore[no-untyped-def]
        for row in self.rows:
            yield row

    async def prices(self, *, game: str = "csgo") -> list[dict[str, object]]:
        return []


async def test_a_collapsed_snapshot_is_refused(db_engine) -> None:  # type: ignore[no-untyped-def]
    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    full = [SnapshotRow(i, f"P250 | Skin {i} (Field-Tested)", 1000 + i, True) for i in range(10)]
    await sync_prices(factory, _Client(full), redis)  # type: ignore[arg-type]
    result = await sync_prices(factory, _Client(full[:2]), redis)  # type: ignore[arg-type]
    assert result.refused is True
    assert (result.changed, result.deactivated, result.stubs) == (0, 0, 0)
    async with factory() as db:
        active = (await db.execute(select(SkinItem).where(SkinItem.active.is_(True)))).all()
    assert len(active) == 10  # no previously active row went inactive
    await redis.aclose()


async def test_a_snapshot_without_auto_listings_is_refused(db_engine) -> None:  # type: ignore[no-untyped-def]
    """Names all present, but none counted as ``auto`` (say the CSV's ``auto`` column
    changed format): applying it would take every row inactive, so it is refused."""
    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    full = [SnapshotRow(i, f"P250 | Skin {i} (Field-Tested)", 1000 + i, True) for i in range(10)]
    await sync_prices(factory, _Client(full), redis)  # type: ignore[arg-type]
    version = await catalog_version(redis)
    no_auto = [SnapshotRow(r.item_id, r.name, r.price_units, False) for r in full]
    result = await sync_prices(factory, _Client(no_auto), redis)  # type: ignore[arg-type]
    assert result.refused is True
    assert (result.changed, result.deactivated, result.stubs) == (0, 0, 0)
    async with factory() as db:
        active = (await db.execute(select(SkinItem).where(SkinItem.active.is_(True)))).all()
    assert len(active) == 10
    assert await catalog_version(redis) == version  # no cache bump either
    await redis.aclose()


async def test_inactive_rows_absent_from_the_snapshot_are_not_touched(
    db_session: AsyncSession,
) -> None:
    """Only active rows are candidates for deactivation: an already inactive row that
    is not in the snapshot keeps its columns (including ``updated_at``)."""
    first = [
        SnapshotRow(1, "AK-47 | Redline (Field-Tested)", 27867, True),
        SnapshotRow(2, "AWP | Asiimov (Field-Tested)", 50000, False),  # inactive stub
    ]
    await apply_prices(db_session, aggregate(first), meta=[], at=now())
    await db_session.commit()
    db_session.expire_all()
    awp = (
        await db_session.execute(
            select(SkinItem).where(SkinItem.market_hash_name == "AWP | Asiimov (Field-Tested)")
        )
    ).scalar_one()
    before = (awp.active, awp.price_hash, awp.count_all, awp.updated_at)
    assert before[0] is False
    assert before[1] is not None

    statements: list[str] = []

    def _capture(*args: object) -> None:
        statements.append(str(args[2]))  # (conn, cursor, statement, ...)

    engine = db_session.bind.sync_engine  # type: ignore[union-attr]
    event.listen(engine, "before_cursor_execute", _capture)
    try:
        result = await apply_prices(db_session, aggregate(first[:1]), meta=[], at=now())
    finally:
        event.remove(engine, "before_cursor_execute", _capture)
    await db_session.commit()
    assert result.deactivated == 0
    db_session.expire_all()
    await db_session.refresh(awp)
    assert (awp.active, awp.price_hash, awp.count_all, awp.updated_at) == before
    # Nothing to deactivate, so no ``IN (...)`` UPDATE was sent at all.
    assert not any(s.lstrip().upper().startswith("UPDATE") for s in statements)
