"""``fx.service.refresh_with_fallback``: cbu.uz first; when it fails and the newest rate is old
enough, the fallback source; a fresh rate (a manual one too) is never replaced by it."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from csmarket.core import clock
from csmarket.core.redis import get_redis
from csmarket.modules.fx.cbu import CbuError
from csmarket.modules.fx.service import rate_age, record_snapshot, refresh_with_fallback
from sqlalchemy.ext.asyncio import AsyncSession

AFTER = timedelta(hours=12)


async def _cbu() -> Decimal:
    return Decimal("12004.02")


async def _down() -> Decimal:
    raise CbuError("ConnectTimeout")


async def _fallback() -> Decimal:
    return Decimal("11983.7534")


async def test_cbu_answers_and_the_fallback_is_not_asked(db_session: AsyncSession) -> None:
    got = await refresh_with_fallback(
        db_session, get_redis(), primary=_cbu, fallback=_down, fallback_after=AFTER
    )
    assert (got.rate, got.source) == (Decimal("12004.02"), "cbu")


async def test_cbu_down_and_no_rate_uses_the_fallback(db_session: AsyncSession) -> None:
    got = await refresh_with_fallback(
        db_session, get_redis(), primary=_down, fallback=_fallback, fallback_after=AFTER
    )
    assert (got.rate, got.source) == (Decimal("11983.7534"), "er-api")


async def test_cbu_down_but_a_fresh_rate_keeps_it(db_session: AsyncSession) -> None:
    await record_snapshot(db_session, rate=Decimal("12000"), source="manual")
    await db_session.commit()
    with pytest.raises(CbuError):
        await refresh_with_fallback(
            db_session, get_redis(), primary=_down, fallback=_fallback, fallback_after=AFTER
        )


async def test_cbu_down_and_an_old_rate_uses_the_fallback(db_session: AsyncSession) -> None:
    base = clock.now()
    clock.set_clock(lambda: base - timedelta(hours=13))
    try:
        await record_snapshot(db_session, rate=Decimal("11965.51"), source="cbu")
        await db_session.commit()
    finally:
        clock.reset_clock()
    age = await rate_age(db_session)
    assert age is not None
    assert age >= timedelta(hours=13)
    got = await refresh_with_fallback(
        db_session, get_redis(), primary=_down, fallback=_fallback, fallback_after=AFTER
    )
    assert got.source == "er-api"


async def test_no_rate_has_no_age(db_session: AsyncSession) -> None:
    assert await rate_age(db_session) is None
