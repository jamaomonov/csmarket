"""A status-6 trade is conclusive only when it is OUR trade (fix round 1, Task 9).

Waxpeer keeps a refused attempt under the order's ``project_id`` as status 6. A lost answer
on a later buy (the substitute) must never be "resolved" by that refused attempt: no
refund, no pinned Waxpeer id; after ``order_unconfirmed_minutes`` an admin decides (R3), and
the substitute's live trade, once it shows, is adopted. The pre-buy lookup never adopts a
6-only answer either.
"""

from __future__ import annotations

from datetime import timedelta

from csmarket.core import clock as core_clock
from csmarket.modules.orders.buying import attempt_buy
from csmarket.modules.orders.models import Order
from csmarket.modules.skins.api import WaxpeerBuyRefusedError, WaxpeerUnavailableError
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.fake_trade_client import FakeTradeClient
from tests.integration.trade_sweeps_kit import (  # noqa: F401 -- fixtures by name
    WAXPEER_ID,
    Clock,
    attentions,
    balance,
    clock_fixture,
    db_fixture,
    fake_fixture,
    load,
    order_in,
    reconcile_once,
    set_trade,
    sweep_settings,
    trade,
)

SOLD = WaxpeerBuyRefusedError("Item not found", new_price_units=None)
REFUSED_ID = 111


async def _pending(db: AsyncSession, **trade_values: object) -> Order:
    """A paid order the worker claimed: its buy is pending, nothing bought yet."""
    values: dict[str, object] = {"waxpeer_id": None, "status": None, "buy_pending": True}
    values.update(trade_values)
    return await order_in(db, "buying", **values)


async def _attempt(db: AsyncSession, fake: FakeTradeClient, order: Order) -> str:
    return await attempt_buy(db, fake, order_id=order.id)


# --- the reviewer's scenario ---------------------------------------------------------------


async def test_a_lost_answer_is_never_refunded_on_a_refused_trade_record(
    db: AsyncSession, fake: FakeTradeClient, clock: Clock
) -> None:
    order0 = await _pending(db)
    fake.buy_raises(WaxpeerUnavailableError("the buy's answer was lost"))
    assert await _attempt(db, fake, order0) == "unconfirmed"
    order, row = await load(db, order0)
    assert (row.buy_pending, row.waxpeer_id) == (False, None)
    assert row.buy_unconfirmed_at is not None

    refused = trade(project_id=order0.id, status=6, id=REFUSED_ID, reason="Item not found")
    fake.lookup_returns([refused])
    clock.advance(seconds=11)
    await reconcile_once(db, fake)
    order, row = await load(db, order0)
    assert (order.status, order.refunded_at) == ("buying", None)
    assert (row.waxpeer_id, row.status, row.attention_reason) == (None, None, None)
    assert await balance(db, order) == 0

    before = attentions("buy_unconfirmed")
    clock.advance(minutes=11)
    await reconcile_once(db, fake)
    order, row = await load(db, order0)
    assert (order.status, order.refunded_at) == ("buying", None)
    assert row.attention_reason == "buy_unconfirmed"
    assert row.waxpeer_id is None
    assert attentions("buy_unconfirmed") == before + 1

    live = trade(project_id=order0.id, status=2, id=WAXPEER_ID)
    fake.lookup_returns([refused, live])
    clock.advance(seconds=11)
    await reconcile_once(db, fake)
    order, row = await load(db, order0)
    assert (row.waxpeer_id, row.status) == (WAXPEER_ID, 2)  # the lost buy, adopted
    assert row.attention_reason is None  # a live trade answers the lost buy (ruling Q)
    assert order.status == "buying"
    assert fake.buy_calls == 1  # never bought again


async def test_a_known_trade_that_fails_is_conclusive(
    db: AsyncSession, fake: FakeTradeClient, clock: Clock
) -> None:
    order0 = await order_in(db, "trade_sent", status=4, buy_unconfirmed_at=clock.now())
    refused = trade(project_id=order0.id, status=6, id=REFUSED_ID)
    ours = trade(project_id=order0.id, status=6, reason="Buyer failed to accept")
    fake.lookup_returns([refused, ours])
    await reconcile_once(db, fake)
    order, _ = await load(db, order0)
    assert (order.status, order.failure_reason) == ("returned", "not_accepted")


async def test_a_found_live_trade_clears_buy_unconfirmed(
    db: AsyncSession, fake: FakeTradeClient, clock: Clock
) -> None:
    order0 = await order_in(
        db,
        "buying",
        waxpeer_id=None,
        status=None,
        buy_unconfirmed_at=clock.now() - timedelta(minutes=30),
        attention_reason="buy_unconfirmed",
    )
    fake.lookup_returns([trade(project_id=order0.id, status=4)])
    await reconcile_once(db, fake)
    order, row = await load(db, order0)
    assert order.status == "trade_sent"
    assert (row.attention_reason, row.waxpeer_id) == (None, WAXPEER_ID)


async def test_an_ambiguous_attention_stays_for_a_human(
    db: AsyncSession, fake: FakeTradeClient
) -> None:
    order0 = await order_in(db, "buying", attention_reason="ambiguous_trade")
    fake.lookup_returns([trade(project_id=order0.id, status=4)])
    await reconcile_once(db, fake)
    order, row = await load(db, order0)
    assert order.status == "trade_sent"
    assert row.attention_reason == "ambiguous_trade"


# --- the pre-buy lookup ----------------------------------------------------------------------


async def test_a_6_only_lookup_is_not_adopted_the_order_is_bought(
    db: AsyncSession, fake: FakeTradeClient
) -> None:
    order0 = await _pending(db)
    fake.lookup_returns([trade(project_id=order0.id, status=6, id=REFUSED_ID)])
    assert await _attempt(db, fake, order0) == "bought"
    order, row = await load(db, order0)
    assert fake.buy_calls == 1
    assert row.waxpeer_id not in (None, REFUSED_ID)
    assert (order.status, row.status, row.buy_pending) == ("buying", 0, False)


async def test_a_6_only_lookup_after_a_lost_answer_buys_nothing(
    db: AsyncSession, fake: FakeTradeClient
) -> None:
    order0 = await _pending(db, buy_unconfirmed_at=core_clock.now())
    fake.lookup_returns([trade(project_id=order0.id, status=6, id=REFUSED_ID)])
    assert await _attempt(db, fake, order0) == "nothing_to_do"
    order, row = await load(db, order0)
    assert fake.buy_calls == 0
    assert (row.waxpeer_id, row.buy_pending) == (None, False)  # reconcile's rule decides
    assert (order.status, order.refunded_at) == ("buying", None)


async def test_an_empty_lookup_after_a_lost_answer_buys_nothing(
    db: AsyncSession, fake: FakeTradeClient
) -> None:
    """The belt (final review minor 2): a ``buy_pending`` trade that still carries a lost
    answer is parked whatever the lookup shows — empty included — never bought again."""
    order0 = await _pending(db, buy_unconfirmed_at=core_clock.now())
    assert await _attempt(db, fake, order0) == "nothing_to_do"
    order, row = await load(db, order0)
    assert (fake.lookup_calls, fake.buy_calls) == (1, 0)
    assert (row.buy_pending, row.buy_unconfirmed_at is not None) == (False, True)
    assert (order.status, order.refunded_at) == ("buying", None)


async def test_a_6_only_lookup_that_was_accepted_buys_nothing(
    db: AsyncSession, fake: FakeTradeClient
) -> None:
    order0 = await _pending(db)
    fake.lookup_returns([trade(project_id=order0.id, status=6, penalties={"rollback_fee": 200})])
    assert await _attempt(db, fake, order0) == "ambiguous"
    order, row = await load(db, order0)
    assert fake.buy_calls == 0
    assert (row.attention_reason, row.buy_pending) == ("ambiguous_trade", False)
    assert order.refunded_at is None


# --- a known trade Waxpeer stops reporting ---------------------------------------------------


async def test_a_known_trade_missing_from_the_lookup_needs_attention_once(
    db: AsyncSession, fake: FakeTradeClient, clock: Clock
) -> None:
    order0 = await order_in(db, "trade_sent", status=4, last_polled_at=clock.now())
    fake.lookup_returns([])
    clock.advance(minutes=9)
    await reconcile_once(db, fake)
    _, row = await load(db, order0)
    assert row.attention_reason is None
    before = attentions("ambiguous_trade")
    clock.advance(minutes=2)
    await reconcile_once(db, fake)
    clock.advance(seconds=11)
    await reconcile_once(db, fake)
    order, row = await load(db, order0)
    assert row.attention_reason == "ambiguous_trade"
    assert (order.status, order.refunded_at) == ("trade_sent", None)
    assert attentions("ambiguous_trade") == before + 1


async def test_a_park_on_rows_moved_meanwhile_writes_nothing(
    db: AsyncSession, fake: FakeTradeClient
) -> None:
    order0 = await _pending(db, buy_unconfirmed_at=core_clock.now())
    fake.lookup_returns([trade(project_id=order0.id, status=6, id=REFUSED_ID)])

    async def settled_meanwhile() -> None:
        await set_trade(db, order0, buy_pending=False, attention_reason="ambiguous_trade")

    fake.before_lookup = settled_meanwhile
    assert await _attempt(db, fake, order0) == "nothing_to_do"
    _, row = await load(db, order0)
    assert (row.buy_pending, row.attention_reason, row.waxpeer_id) == (
        False,
        "ambiguous_trade",
        None,
    )
