"""``fx.service``: snapshots in Postgres, a Redis copy, the 7-day and 20-hour rules."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from csmarket.core import clock
from csmarket.core import config as cfg
from csmarket.core.redis import get_redis
from csmarket.modules.fx.models import FxSnapshot
from csmarket.modules.fx.service import (
    REDIS_KEY,
    current_usd_uzs,
    record_snapshot,
    refresh_usd_uzs,
)
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession


async def _fetch_12700() -> Decimal:
    return Decimal("12700")


async def test_no_snapshot_means_no_rate(db_session: AsyncSession) -> None:
    assert await current_usd_uzs(db_session, get_redis(), max_age_days=7) is None


async def test_refresh_records_and_caches(db_session: AsyncSession) -> None:
    got = await refresh_usd_uzs(db_session, get_redis(), fetch=_fetch_12700)
    await db_session.commit()
    assert got.rate == Decimal("12700")
    assert got.source == "cbu"
    assert await get_redis().get(REDIS_KEY) is not None
    again = await current_usd_uzs(db_session, get_redis(), max_age_days=7)
    assert again is not None
    assert again.snapshot_id == got.snapshot_id


async def test_same_rate_within_20h_does_not_add_a_row(db_session: AsyncSession) -> None:
    await refresh_usd_uzs(db_session, get_redis(), fetch=_fetch_12700)
    await refresh_usd_uzs(db_session, get_redis(), fetch=_fetch_12700)
    await db_session.commit()
    assert await db_session.scalar(select(func.count()).select_from(FxSnapshot)) == 1


async def test_same_rate_after_20h_adds_a_row(db_session: AsyncSession) -> None:
    base = clock.now()
    clock.set_clock(lambda: base - timedelta(hours=21))
    try:
        await refresh_usd_uzs(db_session, get_redis(), fetch=_fetch_12700)
    finally:
        clock.reset_clock()
    await refresh_usd_uzs(db_session, get_redis(), fetch=_fetch_12700)
    assert await db_session.scalar(select(func.count()).select_from(FxSnapshot)) == 2


async def test_a_changed_rate_adds_a_row(db_session: AsyncSession) -> None:
    await refresh_usd_uzs(db_session, get_redis(), fetch=_fetch_12700)

    async def _fetch_12750() -> Decimal:
        return Decimal("12750")

    got = await refresh_usd_uzs(db_session, get_redis(), fetch=_fetch_12750)
    await db_session.commit()
    assert got.rate == Decimal("12750")
    assert await db_session.scalar(select(func.count()).select_from(FxSnapshot)) == 2


async def test_redis_down_falls_back_to_postgres(db_session: AsyncSession) -> None:
    await record_snapshot(db_session, rate=Decimal("12700"), source="cbu")
    await db_session.commit()

    class Broken:
        async def get(self, *_a: object) -> None:
            raise RedisConnectionError("down")

        async def set(self, *_a: object, **_k: object) -> None:
            raise RedisConnectionError("down")

    got = await current_usd_uzs(db_session, Broken(), max_age_days=7)  # type: ignore[arg-type]
    assert got is not None
    assert got.rate == Decimal("12700")


async def test_a_week_old_snapshot_is_no_rate(db_session: AsyncSession) -> None:
    base = clock.now()
    clock.set_clock(lambda: base - timedelta(days=8))
    try:
        await record_snapshot(db_session, rate=Decimal("12700"), source="cbu")
        await db_session.commit()
    finally:
        clock.reset_clock()
    assert await current_usd_uzs(db_session, get_redis(), max_age_days=7) is None


async def test_a_stale_redis_copy_is_ignored(db_session: AsyncSession) -> None:
    base = clock.now()
    clock.set_clock(lambda: base - timedelta(days=8))
    try:
        await refresh_usd_uzs(db_session, get_redis(), fetch=_fetch_12700)
    finally:
        clock.reset_clock()
    assert await get_redis().get(REDIS_KEY) is not None
    assert await current_usd_uzs(db_session, get_redis(), max_age_days=7) is None


@pytest.mark.parametrize("payload", ["not json", '{"rate": "1"}'])
async def test_a_corrupt_redis_copy_falls_back_to_postgres(
    db_session: AsyncSession, payload: str
) -> None:
    await record_snapshot(db_session, rate=Decimal("12700"), source="cbu")
    await db_session.commit()
    await get_redis().set(REDIS_KEY, payload)
    got = await current_usd_uzs(db_session, get_redis(), max_age_days=7)
    assert got is not None
    assert got.rate == Decimal("12700")


async def _fetch_cbu() -> Decimal:
    return Decimal("11790.79")


@pytest.mark.parametrize("cached", [True, False])
async def test_the_buyer_rate_carries_the_uplift_and_the_snapshot_stays_cbu(
    db_session: AsyncSession, cached: bool
) -> None:
    got = await refresh_usd_uzs(db_session, get_redis(), fetch=_fetch_cbu)
    await db_session.commit()
    if not cached:
        await get_redis().delete(REDIS_KEY)
    rate = await current_usd_uzs(db_session, get_redis(), max_age_days=7, uplift_pct=Decimal(1))
    assert rate is not None
    assert (rate.rate, rate.cbu_rate, rate.uplift_pct) == (
        Decimal("11908.70"),
        Decimal("11790.79"),
        Decimal(1),
    )
    assert rate.snapshot_id == got.snapshot_id
    row = await db_session.get(FxSnapshot, got.snapshot_id)
    assert row is not None
    assert row.usd_uzs == Decimal("11790.79")


async def test_the_uplift_comes_from_the_settings_by_default(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CSMARKET_FX_UPLIFT_PCT", "1")
    cfg.get_settings.cache_clear()
    try:
        await refresh_usd_uzs(db_session, get_redis(), fetch=_fetch_cbu)
        await db_session.commit()
        rate = await current_usd_uzs(db_session, get_redis(), max_age_days=7)
        assert rate is not None
        assert (rate.rate, rate.uplift_pct) == (Decimal("11908.70"), Decimal(1))
    finally:
        monkeypatch.delenv("CSMARKET_FX_UPLIFT_PCT")
        cfg.get_settings.cache_clear()


async def test_no_uplift_is_the_cbu_rate(db_session: AsyncSession) -> None:
    await refresh_usd_uzs(db_session, get_redis(), fetch=_fetch_cbu)
    await db_session.commit()
    rate = await current_usd_uzs(db_session, get_redis(), max_age_days=7, uplift_pct=Decimal(0))
    assert rate is not None
    assert (rate.rate, rate.cbu_rate) == (Decimal("11790.79"), Decimal("11790.79"))
