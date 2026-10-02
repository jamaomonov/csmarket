"""``orders.buying.attempt_buy`` under races and time: the lease comes before the read, so
two attempts never buy one order; a release is the lease holder's only; an attempt never
outlives its lease; a buy that may have reached Waxpeer is never left ``buy_pending``."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Any

import pytest
from csmarket.core import clock
from csmarket.core.config import Settings, get_settings
from csmarket.modules.orders import buy_lease, buy_writes, buying
from csmarket.modules.orders.api import Order, SkinTrade, attempt_buy
from csmarket.modules.skins.api import (
    WaxpeerBuy,
    WaxpeerError,
    WaxpeerForbiddenError,
    WaxpeerUnavailableError,
)
from prometheus_client import REGISTRY
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from tests.integration.fake_trade_client import FakeTradeClient
from tests.integration.orders_factory import make_due
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
    take_lease = buy_lease.take_lease
    competed: list[str] = []

    async def competing_first(db: AsyncSession, oid: str) -> datetime | None:
        if not competed:
            competed.append("running")  # the competitor's own lease goes straight through
            competed[0] = await _go(db, fake, oid, settings)
        return await take_lease(db, oid)

    monkeypatch.setattr(buying, "take_lease", competing_first)
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
    await make_due(db_session, order)
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


async def _slow(seconds: float = 5.0) -> None:
    await asyncio.sleep(seconds)


async def _lease_held(db: AsyncSession, order: Order) -> bool:
    row, _ = await load(db, order)
    return row.next_check_at is not None and row.next_check_at > clock.now()


async def test_a_timeout_after_a_successful_answer_is_unconfirmed_never_rebought(
    db_session: AsyncSession,
    fake: FakeTradeClient,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(buying, "ATTEMPT_BUDGET", timedelta(milliseconds=200))
    record = buy_writes.record_bought

    async def slow_record(*args: Any, **kwargs: Any) -> str:
        await _slow()
        return await record(*args, **kwargs)

    monkeypatch.setattr(buying, "record_bought", slow_record)
    order = await _buying(db_session)
    order_id = order.id
    assert await _go(db_session, fake, order_id, settings) == "unconfirmed"
    _, trade = await load(db_session, order)
    assert trade.buy_pending is False
    assert trade.buy_unconfirmed_at is not None
    assert await _go(db_session, fake, order_id, settings) == "nothing_to_do"
    assert fake.buy_calls == 1


async def test_a_timeout_on_a_lock_wait_while_recording_is_unconfirmed(
    db_engine: AsyncEngine,
    db_session: AsyncSession,
    fake: FakeTradeClient,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The cancellation lands mid-statement (the order row is locked elsewhere).

    The budget must outlast everything before the buy (lease, read, lookup) even on a loaded
    CI runner, and end while the lock is still held: 1 s of budget, 3 s of lock.
    """
    monkeypatch.setattr(buying, "ATTEMPT_BUDGET", timedelta(seconds=1))
    order = await _buying(db_session)
    order_id = order.id
    other = async_sessionmaker(bind=db_engine, expire_on_commit=False)()
    tasks: list[asyncio.Task[None]] = []

    async def lock_the_order() -> None:
        await other.execute(select(Order).where(Order.id == order_id).with_for_update())

        async def let_go() -> None:
            await asyncio.sleep(3)
            await other.commit()

        tasks.append(asyncio.create_task(let_go()))

    fake.before_buy = lock_the_order
    try:
        assert await _go(db_session, fake, order_id, settings) == "unconfirmed"
    finally:
        await asyncio.gather(*tasks)
        await other.close()
    trade = await db_session.get(SkinTrade, order_id, populate_existing=True)
    assert trade is not None  # the rollback expired ``order``: read by id
    assert trade.buy_pending is False
    assert trade.buy_unconfirmed_at is not None
    assert await _go(db_session, fake, order_id, settings) == "nothing_to_do"
    assert fake.buy_calls == 1


async def test_a_timeout_inside_the_unconfirmed_write_after_a_5xx_still_records_it(
    db_session: AsyncSession,
    fake: FakeTradeClient,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(buying, "ATTEMPT_BUDGET", timedelta(milliseconds=200))
    write = buy_writes.unconfirmed

    async def slow_unconfirmed(*args: Any, **kwargs: Any) -> str:
        await _slow()
        return await write(*args, **kwargs)

    monkeypatch.setattr(buying, "unconfirmed", slow_unconfirmed)
    order = await _buying(db_session)
    order_id = order.id
    fake.buy_raises(WaxpeerError("bad gateway", status=502))
    assert await _go(db_session, fake, order_id, settings) == "unconfirmed"
    _, trade = await load(db_session, order)
    assert trade.buy_pending is False
    assert trade.buy_unconfirmed_at is not None
    assert await _go(db_session, fake, order_id, settings) == "nothing_to_do"
    assert fake.buy_calls == 1


async def _secure_fails(db: AsyncSession, snap: object) -> bool:
    raise RuntimeError("database gone")


async def test_a_timeout_whose_unconfirmed_write_fails_keeps_the_lease(
    db_session: AsyncSession,
    fake: FakeTradeClient,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(buying, "ATTEMPT_BUDGET", timedelta(milliseconds=200))
    record = buy_writes.record_bought

    async def slow_record(*args: Any, **kwargs: Any) -> str:
        await _slow()
        return await record(*args, **kwargs)

    monkeypatch.setattr(buying, "record_bought", slow_record)
    monkeypatch.setattr(buy_writes, "secure_sent", _secure_fails)
    order = await _buying(db_session)
    order_id = order.id
    before = REGISTRY.get_sample_value("csmarket_order_buys_total", {"outcome": "unrecorded"})
    # Nothing was written: a distinct outcome, so the stuck gauge has a cause (minor 10).
    assert await _go(db_session, fake, order_id, settings) == "unrecorded"
    after = REGISTRY.get_sample_value("csmarket_order_buys_total", {"outcome": "unrecorded"})
    assert (after or 0) == (before or 0) + 1
    _, trade = await load(db_session, order)
    assert trade.buy_pending is True  # nothing could be written ...
    assert await _lease_held(db_session, order)  # ... so the lease lapses as a dead attempt's
    assert await _go(db_session, fake, order_id, settings) == "nothing_to_do"
    assert fake.buy_calls == 1


async def test_a_failed_unconfirm_raises_the_original_error_and_keeps_the_lease(
    db_session: AsyncSession,
    fake: FakeTradeClient,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order = await _buying(db_session)
    order_id = order.id
    monkeypatch.setattr(buy_writes, "secure_sent", _secure_fails)
    fake.buy_raises(ValueError("unreadable"))
    with pytest.raises(ValueError, match="unreadable"):
        await _go(db_session, fake, order_id, settings)
    _, trade = await load(db_session, order)
    assert trade.buy_pending is True
    assert await _lease_held(db_session, order)
    assert await _go(db_session, fake, order_id, settings) == "nothing_to_do"
    assert fake.buy_calls == 1


async def test_a_timeout_after_another_writer_recorded_the_buy_changes_nothing(
    db_session: AsyncSession,
    fake: FakeTradeClient,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(buying, "ATTEMPT_BUDGET", timedelta(milliseconds=200))
    record = buy_writes.record_bought

    async def record_then_hang(*args: Any, **kwargs: Any) -> str:
        await record(*args, **kwargs)
        await _slow()
        return "bought"

    monkeypatch.setattr(buying, "record_bought", record_then_hang)
    order = await _buying(db_session)
    assert await _go(db_session, fake, order.id, settings) == "nothing_to_do"
    _, trade = await load(db_session, order)
    assert trade.buy_unconfirmed_at is None
    assert trade.waxpeer_id == 50_000_002


async def test_securing_a_sent_buy_on_an_order_that_left_buying_flags_it(
    db_session: AsyncSession,
) -> None:
    order = await _buying(db_session)
    row, _ = await load(db_session, order)
    row.status = "delivered"
    await db_session.commit()
    snap = buy_writes.BuySnapshot(
        order_id=order.id,
        number=order.number,
        skin_item_id=order.skin_item_id,
        listing_id=order.listing_id,
        paid_units=COST,
    )
    assert await buy_writes.secure_sent(db_session, snap) is True
    _, trade = await load(db_session, order)
    assert trade.buy_pending is False
    assert trade.attention_reason == "ambiguous_trade"


async def test_a_broken_session_is_given_back_and_a_failed_release_is_swallowed(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    closed: list[bool] = []

    class _Broken:
        async def rollback(self) -> None:
            raise RuntimeError("connection gone")

        async def close(self) -> None:
            closed.append(True)

    await buy_lease.discard(_Broken())  # type: ignore[arg-type]  # a session-shaped fake
    assert closed == [True]

    async def release_fails(db: AsyncSession, order_id: str, lease: datetime) -> None:
        raise RuntimeError("database gone")

    monkeypatch.setattr(buy_lease, "release", release_fails)
    await buy_lease.release_fresh(db_session, "an-order", clock.now())  # never raises
