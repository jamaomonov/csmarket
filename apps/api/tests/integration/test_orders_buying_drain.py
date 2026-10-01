"""``orders.buying.drain_paid``: the worker claims paid orders, oldest first, each once, and
buys them; a poisoned order never stops the batch; no log line carries the trade link."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest
from csmarket.core import clock
from csmarket.core.config import Settings, get_settings
from csmarket.modules.orders.api import Order, SkinTrade, drain_paid
from csmarket.modules.skins.api import WaxpeerBuy, WaxpeerUnavailableError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from tests.integration.fake_trade_client import FakeTradeClient
from tests.integration.orders_factory import make_order

#: Redrawn: a fake partner and token, never a real account's.
LINK = "https://steamcommunity.com/tradeoffer/new/?partner=40404040&token=ZzQx9Lk2"


@pytest.fixture
def settings() -> Settings:
    return get_settings().model_copy(update={"waxpeer_api_key": "test-key-not-real"})


async def _paid(db: AsyncSession, *, minutes_ago: int = 0, **overrides: object) -> Order:
    values: dict[str, Any] = {
        "status": "paid",
        "paid_with": "payme",
        "paid_at": clock.now() - timedelta(minutes=minutes_ago),
        "price_uzs": Decimal(171_800),
    }
    values.update(overrides)
    return await make_order(db, **values)


async def _trade(db: AsyncSession, order: Order) -> SkinTrade | None:
    return await db.scalar(
        select(SkinTrade)
        .where(SkinTrade.order_id == order.id)
        .execution_options(populate_existing=True)
    )


async def _order(db: AsyncSession, order: Order) -> Order:
    row = await db.scalar(
        select(Order).where(Order.id == order.id).execution_options(populate_existing=True)
    )
    assert row is not None
    return row


async def test_redrain_of_a_buying_order_buys_nothing(
    db_session: AsyncSession, settings: Settings
) -> None:
    await _paid(db_session)
    fake = FakeTradeClient()
    fake.lookup_returns([])
    fake.buy_returns(WaxpeerBuy(id=5, price_units=10_000))
    assert await drain_paid(db_session, client=fake, settings=settings) == 1
    assert await drain_paid(db_session, client=fake, settings=settings) == 0
    assert fake.buy_calls == 1


async def test_the_claim_takes_the_oldest_paid_orders_and_opens_their_trades(
    db_session: AsyncSession, settings: Settings
) -> None:
    newest = await _paid(db_session, minutes_ago=1)
    oldest = await _paid(db_session, minutes_ago=3)
    middle = await _paid(db_session, minutes_ago=2)
    fake = FakeTradeClient()
    fake.lookup_raises(WaxpeerUnavailableError("down"))  # claimed, not bought yet
    assert await drain_paid(db_session, client=fake, settings=settings, limit=2) == 2
    for order in (oldest, middle):
        row = await _order(db_session, order)
        assert row.status == "buying"
        assert row.claimed_at is not None
        assert row.claimed_by is not None
        assert ":" in row.claimed_by
        trade = await _trade(db_session, order)
        assert trade is not None
        assert (trade.project_id, trade.listing_id, trade.paid_units) == (
            order.id,
            order.listing_id,
            order.cost_units,
        )
        assert trade.buy_pending is True
    assert (await _order(db_session, newest)).status == "paid"
    assert await _trade(db_session, newest) is None


async def test_two_workers_draining_concurrently_claim_disjoint_orders(
    db_engine: AsyncEngine, db_session: AsyncSession, settings: Settings
) -> None:
    orders = [await _paid(db_session, minutes_ago=i) for i in range(4)]
    fake = FakeTradeClient()
    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)

    async def worker() -> int:
        async with factory() as db:
            return await drain_paid(db, client=fake, settings=settings, limit=2)

    claimed = await asyncio.gather(worker(), worker())
    assert sum(claimed) == 4
    assert sorted(project for _, _, project in fake.bought) == sorted(o.id for o in orders)
    assert fake.buy_calls == 4


async def test_an_exception_inside_one_buy_does_not_stop_the_drain(
    db_session: AsyncSession, settings: Settings
) -> None:
    poisoned = await _paid(db_session, minutes_ago=3)
    unsure = await _paid(db_session, minutes_ago=2, listing_id=1_001)
    healthy = await _paid(db_session, minutes_ago=1, listing_id=1_002)
    fake = FakeTradeClient()
    fake.lookup_fails_for(poisoned.id, RuntimeError("a bug before any buy"))
    fake.refuse(1_001, RuntimeError("a bug after the buy was sent"))
    assert await drain_paid(db_session, client=fake, settings=settings) == 3
    assert [b[2] for b in fake.bought] == [healthy.id]
    # Nothing was sent: still buying with the buy pending (the sweep retries after the lease).
    trade = await _trade(db_session, poisoned)
    assert (await _order(db_session, poisoned)).status == "buying"
    assert trade is not None
    assert trade.buy_pending
    # The buy may have reached Waxpeer: unconfirmed, resolved by lookup, never rebought.
    trade = await _trade(db_session, unsure)
    assert trade is not None
    assert trade.buy_pending is False
    assert trade.buy_unconfirmed_at is not None
    assert (await _order(db_session, healthy)).status == "buying"


async def test_no_log_line_carries_the_trade_link(
    db_session: AsyncSession,
    settings: Settings,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    await _paid(db_session, minutes_ago=3, trade_link=LINK)
    await _paid(db_session, minutes_ago=2, trade_link=LINK, listing_id=2_002)
    await _paid(db_session, minutes_ago=1, trade_link="https://steamcommunity.com/broken")
    fake = FakeTradeClient()
    fake.refuse(2_002, WaxpeerUnavailableError("timeout"))
    assert await drain_paid(db_session, client=fake, settings=settings) == 3
    out = capsys.readouterr()
    logged = caplog.text + out.out + out.err
    assert "orders.buy" in logged
    for leak in ("ZzQx9Lk2", "40404040", "partner=", "steamcommunity", "https://", "api="):
        assert leak not in logged, leak


async def test_the_drain_without_a_client_uses_the_process_client(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from csmarket.modules.orders import buying

    fake = FakeTradeClient()
    monkeypatch.setattr(buying, "trade_client", lambda settings: fake)
    assert await drain_paid(db_session) == 0  # nothing paid: no client is built
    await _paid(db_session)
    assert await drain_paid(db_session) == 1
    assert fake.buy_calls == 1
