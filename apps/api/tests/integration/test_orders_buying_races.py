"""``orders.buying.attempt_buy`` under races and time: the lease comes before the read, so
two attempts never buy one order; a release is the lease holder's only; an attempt never
outlives its lease; a buy that may have reached Waxpeer is never left ``buy_pending``."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

import pytest
from csmarket.core import clock
from csmarket.core.config import Settings, get_settings
from csmarket.modules.orders import buying
from csmarket.modules.orders.api import Order, SkinTrade, attempt_buy
from csmarket.modules.skins.api import (
    WaxpeerBuy,
    WaxpeerForbiddenError,
    WaxpeerUnavailableError,
)
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.fake_trade_client import FakeTradeClient
from tests.integration.test_orders_buying import COST, _buying, load


@pytest.fixture
def settings() -> Settings:
    return get_settings().model_copy(update={"waxpeer_api_key": "test-key-not-real"})


@pytest.fixture
def fake() -> FakeTradeClient:
    return FakeTradeClient()


async def _go(db: AsyncSession, fake: FakeTradeClient, order_id: str, settings: Settings) -> str:
    return await attempt_buy(db, fake, order_id=order_id, settings=settings)


@pytest.mark.parametrize("first", ["bought", "unconfirmed"])
async def test_an_attempt_that_read_before_another_settled_the_buy_never_buys_again(
    db_session: AsyncSession,
    fake: FakeTradeClient,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    first: str,
) -> None:
    """A full competing attempt runs just before this one takes its lease."""
    order = await _buying(db_session)
    order_id = order.id
    if first == "unconfirmed":
        fake.buy_raises(WaxpeerUnavailableError("timeout"))
    take_lease = buying._take_lease
    competed: list[str] = []

    async def competing_first(db: AsyncSession, oid: str) -> datetime | None:
        if not competed:
            competed.append("running")  # the competitor's own lease goes straight through
            competed[0] = await _go(db, fake, oid, settings)
        return await take_lease(db, oid)

    monkeypatch.setattr(buying, "_take_lease", competing_first)
    assert await _go(db_session, fake, order_id, settings) == "nothing_to_do"
    assert competed == [first]
    assert fake.buy_calls == 1


async def test_an_order_whose_buy_settled_between_lease_and_read_is_released(
    db_session: AsyncSession,
    fake: FakeTradeClient,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order = await _buying(db_session)
    order_id = order.id
    read = buying._read

    async def settled_meanwhile(db: AsyncSession, oid: str) -> object:
        row, trade = await load(db, order)
        trade.buy_pending = False
        await db.commit()
        return await read(db, oid)

    monkeypatch.setattr(buying, "_read", settled_meanwhile)
    assert await _go(db_session, fake, order_id, settings) == "nothing_to_do"
    row, _ = await load(db_session, order)
    assert row.next_check_at is not None
    assert row.next_check_at <= clock.now()  # released, due again
    assert fake.lookup_calls == 0


async def test_only_the_lease_holder_releases(
    db_session: AsyncSession, fake: FakeTradeClient, settings: Settings
) -> None:
    order = await _buying(db_session)
    later = clock.now() + timedelta(hours=1)

    async def someone_else_holds_it_now() -> None:
        row, _ = await load(db_session, order)
        row.next_check_at = later
        await db_session.commit()

    fake.before_buy = someone_else_holds_it_now
    assert await _go(db_session, fake, order.id, settings) == "bought"
    row, _ = await load(db_session, order)
    assert row.next_check_at == later


async def test_an_attempt_that_runs_out_of_time_mid_buy_is_unconfirmed(
    db_session: AsyncSession,
    fake: FakeTradeClient,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(buying, "ATTEMPT_BUDGET", timedelta(milliseconds=200))
    order = await _buying(db_session)

    async def hangs() -> None:
        await asyncio.sleep(5)

    fake.before_buy = hangs
    assert await _go(db_session, fake, order.id, settings) == "unconfirmed"
    row, trade = await load(db_session, order)
    assert trade.buy_pending is False
    assert trade.buy_unconfirmed_at is not None
    assert row.next_check_at is not None
    assert row.next_check_at <= clock.now()
    assert await _go(db_session, fake, order.id, settings) == "nothing_to_do"
    assert fake.buy_calls == 1


async def test_an_attempt_that_runs_out_of_time_before_the_buy_sent_nothing(
    db_session: AsyncSession,
    fake: FakeTradeClient,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(buying, "ATTEMPT_BUDGET", timedelta(milliseconds=200))
    order = await _buying(db_session)

    async def hangs() -> None:
        await asyncio.sleep(5)

    fake.before_lookup = hangs
    assert await _go(db_session, fake, order.id, settings) == "lookup_later"
    _, trade = await load(db_session, order)
    assert trade.buy_pending is True
    assert fake.buy_calls == 0


@pytest.mark.parametrize("error", [ValueError("unreadable"), asyncio.CancelledError()])
async def test_an_unexpected_error_from_the_buy_leaves_it_unconfirmed(
    db_session: AsyncSession, fake: FakeTradeClient, settings: Settings, error: BaseException
) -> None:
    order = await _buying(db_session)
    order_id = order.id
    fake.buy_raises(error)
    with pytest.raises(type(error)):
        await _go(db_session, fake, order_id, settings)
    trade = await db_session.get(SkinTrade, order_id, populate_existing=True)
    assert trade is not None
    assert trade.buy_pending is False
    assert trade.buy_unconfirmed_at is not None


async def test_a_new_403_reopens_a_resolved_forbidden_attention(
    db_session: AsyncSession, fake: FakeTradeClient, settings: Settings
) -> None:
    order = await _buying(db_session)
    fake.buy_raises(WaxpeerForbiddenError())
    assert await _go(db_session, fake, order.id, settings) == "forbidden"
    _, trade = await load(db_session, order)
    trade.resolved_at, trade.resolved_by, trade.resolved_note = clock.now(), "admin:x", "seen"
    await db_session.commit()
    assert await _go(db_session, fake, order.id, settings) == "forbidden"
    _, trade = await load(db_session, order)
    assert trade.attention_reason == "waxpeer_forbidden"
    assert (trade.resolved_at, trade.resolved_by, trade.resolved_note) == (None, None, None)


async def test_a_free_buy_answer_records_the_units_offered(
    db_session: AsyncSession, fake: FakeTradeClient, settings: Settings
) -> None:
    order = await _buying(db_session)
    fake.buy_returns(WaxpeerBuy(id=7, price_units=0))
    assert await _go(db_session, fake, order.id, settings) == "bought"
    _, trade = await load(db_session, order)
    assert trade.bought_units == COST


async def test_an_order_with_no_buy_pending_takes_no_lease(
    db_session: AsyncSession, fake: FakeTradeClient, settings: Settings
) -> None:
    order: Order = await _buying(db_session)
    _, trade = await load(db_session, order)
    trade.buy_pending = False
    await db_session.commit()
    assert await _go(db_session, fake, order.id, settings) == "nothing_to_do"
    row, _ = await load(db_session, order)
    assert row.next_check_at is None


async def test_a_failed_unconfirm_still_raises_the_original_error(
    db_session: AsyncSession,
    fake: FakeTradeClient,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order = await _buying(db_session)
    order_id = order.id

    async def broken(db: AsyncSession, snap: object) -> str:
        raise RuntimeError("database gone")

    monkeypatch.setattr(buying, "unconfirmed", broken)
    fake.buy_raises(ValueError("unreadable"))
    with pytest.raises(ValueError, match="unreadable"):
        await _go(db_session, fake, order_id, settings)
