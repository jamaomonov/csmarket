"""``orders.health.measure``: what counts as stuck, and the balance read."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from csmarket.core import clock as core_clock
from csmarket.core.config import get_settings
from csmarket.modules.orders.health import Health, measure
from csmarket.modules.orders.models import Order
from csmarket.modules.skins.api import WaxpeerUnavailableError
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.fake_trade_client import FakeTradeClient
from tests.integration.orders_factory import make_order, make_trade
from tests.integration.trade_sweeps_kit import db_fixture  # noqa: F401 -- fixture


def _ago(**delta: float) -> datetime:
    return core_clock.now() - timedelta(**delta)


async def _measure(db: AsyncSession, client: FakeTradeClient | None = None) -> Health:
    return await measure(db, client, settings=get_settings())


async def _order(
    db: AsyncSession,
    status: str,
    *,
    paid_at: datetime | None = None,
    claimed_at: datetime | None = None,
) -> Order:
    return await make_order(
        db, status=status, paid_with="payme", paid_at=paid_at, claimed_at=claimed_at
    )


async def test_empty_database_is_healthy(db: AsyncSession) -> None:
    assert await _measure(db) == Health(
        paid_stuck=0, buying_stuck=0, trade_sent_unpolled=0, attention=0, waxpeer_balance_usd=None
    )


@pytest.mark.parametrize(("minutes", "stuck"), [(4, 0), (6, 1)])
async def test_paid_is_stuck_after_five_minutes(db: AsyncSession, minutes: int, stuck: int) -> None:
    await _order(db, "paid", paid_at=_ago(minutes=minutes))
    assert (await _measure(db)).paid_stuck == stuck


async def test_only_paid_orders_count_as_paid_stuck(db: AsyncSession) -> None:
    await _order(db, "buying", paid_at=_ago(hours=2), claimed_at=_ago(minutes=1))
    await _order(db, "delivered", paid_at=_ago(hours=2))
    assert (await _measure(db)).paid_stuck == 0


@pytest.mark.parametrize(("minutes", "stuck"), [(29, 0), (31, 1)])
async def test_buying_is_stuck_after_thirty_minutes_claimed(
    db: AsyncSession, minutes: int, stuck: int
) -> None:
    order = await _order(db, "buying", paid_at=_ago(hours=2), claimed_at=_ago(minutes=minutes))
    await make_trade(db, order)
    assert (await _measure(db)).buying_stuck == stuck


async def test_buying_without_a_trade_row_counts(db: AsyncSession) -> None:
    await _order(db, "buying", paid_at=_ago(hours=2), claimed_at=_ago(minutes=45))
    assert (await _measure(db)).buying_stuck == 1


async def test_buying_with_an_open_attention_is_not_stuck_but_is_attention(
    db: AsyncSession,
) -> None:
    order = await _order(db, "buying", paid_at=_ago(hours=2), claimed_at=_ago(minutes=45))
    await make_trade(db, order, attention_reason="waxpeer_forbidden")
    health = await _measure(db)
    assert (health.buying_stuck, health.attention) == (0, 1)


async def test_a_resolved_attention_is_neither_attention_nor_a_hiding_place(
    db: AsyncSession,
) -> None:
    order = await _order(db, "buying", paid_at=_ago(hours=2), claimed_at=_ago(minutes=45))
    await make_trade(db, order, attention_reason="rolled_back", resolved_at=_ago(minutes=1))
    health = await _measure(db)
    assert (health.buying_stuck, health.attention) == (1, 0)


@pytest.mark.parametrize(
    ("polled_minutes_ago", "stuck"),
    [(29, 0), (31, 1), (None, 1)],
)
async def test_trade_sent_unpolled_after_thirty_minutes_or_never(
    db: AsyncSession, polled_minutes_ago: int | None, stuck: int
) -> None:
    # The poll time is taken when the test runs, not when pytest collects it: a slow run
    # (CI) used to age a "29 minutes ago" parameter past the 30-minute line.
    last_polled = None if polled_minutes_ago is None else _ago(minutes=polled_minutes_ago)
    order = await _order(db, "trade_sent", paid_at=_ago(hours=2))
    await make_trade(db, order, last_polled_at=last_polled)
    assert (await _measure(db)).trade_sent_unpolled == stuck


async def test_balance_is_units_over_a_thousand(db: AsyncSession) -> None:
    fake = FakeTradeClient()
    fake.balance_returns(48_250)
    assert (await _measure(db, fake)).waxpeer_balance_usd == Decimal("48.250")


async def test_balance_error_is_none_not_a_crash(db: AsyncSession) -> None:
    fake = FakeTradeClient()
    fake.balance_raises(WaxpeerUnavailableError("down"))
    health = await _measure(db, fake)
    assert health.waxpeer_balance_usd is None


async def test_unexpected_balance_error_is_none_too(db: AsyncSession) -> None:
    fake = FakeTradeClient()
    fake.balance_raises(RuntimeError("anything"))
    assert (await _measure(db, fake)).waxpeer_balance_usd is None


# --- the cached balance (M4b T9, ruling R10) ----------------------------------------------


async def test_the_cached_balance_reads_back() -> None:
    from csmarket.core.redis import get_redis
    from csmarket.modules.orders.health import cache_balance, cached_balance

    at = datetime(2026, 10, 2, 9, 0, tzinfo=core_clock.now().tzinfo)
    await cache_balance(get_redis(), Decimal("123.456"), at=at)
    assert await cached_balance(get_redis()) == (Decimal("123.456"), at)
    assert 0 < await get_redis().ttl("orders:waxpeer:balance") <= 3600


async def test_no_cached_balance_reads_as_nothing() -> None:
    from csmarket.core.redis import get_redis
    from csmarket.modules.orders.health import cached_balance

    assert await cached_balance(get_redis()) == (None, None)
    await get_redis().set("orders:waxpeer:balance", "not json")
    assert await cached_balance(get_redis()) == (None, None)
