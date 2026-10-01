"""``orders.trades.apply`` through the reconcile sweep: Waxpeer's status → the order.

The status half of YuPay's skin fulfiller suite, ported onto ``trades`` / ``sweeps``: an
offer followed to acceptance, a declined offer refunded to the balance, a rollback after
acceptance kept as money spent (R3), a lost buy answer adopted by lookup and never rebought,
the trade picked by Waxpeer's id. A scripted Waxpeer stands in; the database is real.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from csmarket.core import clock as core_clock
from csmarket.core.errors import ConflictError
from csmarket.modules.orders.models import Order
from csmarket.modules.orders.trades import apply
from sqlalchemy.ext.asyncio import AsyncSession
from structlog.testing import capture_logs

from tests.integration.fake_trade_client import FakeTradeClient
from tests.integration.trade_sweeps_kit import (  # noqa: F401 -- fixtures by name
    PRICE,
    RELEASE,
    WAXPEER_ID,
    Clock,
    attentions,
    balance,
    buying_order_fixture,
    clock_fixture,
    db_fixture,
    delivered_order_fixture,
    fake_fixture,
    load,
    order_in,
    reconcile_once,
    set_order,
    set_trade,
    trade,
    trade_sent_order_fixture,
    watch_once,
)

# --- the offer to acceptance ---------------------------------------------------------------


async def test_a_sent_offer_moves_buying_to_trade_sent(
    db: AsyncSession, fake: FakeTradeClient, buying_order: Order
) -> None:
    fake.lookup_returns([trade(project_id=buying_order.id, status=4)])
    assert await reconcile_once(db, fake) == 1
    order, row = await load(db, buying_order)
    assert order.status == "trade_sent"
    assert (row.status, row.trade_id, row.accepted_at) == (4, "7700112233", None)
    assert row.seller["name"] == "redrawn_seller"
    assert row.last_polled_at is not None


async def test_an_accepted_offer_is_delivered_with_accepted_at(
    db: AsyncSession, fake: FakeTradeClient, trade_sent_order: Order
) -> None:
    fake.lookup_returns([trade(project_id=trade_sent_order.id, status=4, release_date=RELEASE)])
    await reconcile_once(db, fake)
    order, row = await load(db, trade_sent_order)
    assert order.status == "delivered"
    assert order.delivered_at is not None
    assert row.release_date == RELEASE
    assert row.accepted_at is not None
    assert order.refunded_at is None


async def test_bought_to_accepted_in_one_tick_delivers_from_buying(
    db: AsyncSession, fake: FakeTradeClient, buying_order: Order
) -> None:
    fake.lookup_returns([trade(project_id=buying_order.id, status=4, release_date=RELEASE)])
    await reconcile_once(db, fake)
    order, row = await load(db, buying_order)
    assert order.status == "delivered"
    assert row.accepted_at is not None


async def test_a_released_trade_is_delivered(
    db: AsyncSession, fake: FakeTradeClient, trade_sent_order: Order
) -> None:
    fake.lookup_returns(
        [trade(project_id=trade_sent_order.id, status=5, release_date=RELEASE, is_released=True)]
    )
    await reconcile_once(db, fake)
    order, row = await load(db, trade_sent_order)
    assert order.status == "delivered"
    assert (row.status, row.is_released) == (5, True)


async def test_waxpeer_still_buying_changes_nothing_but_the_mirror(
    db: AsyncSession, fake: FakeTradeClient
) -> None:
    orders = [await order_in(db, "buying", status=1) for _ in range(4)]
    fake.lookup_returns(
        [
            trade(project_id=o.id, status=status)
            for o, status in zip(orders, (0, 1, 2, -1), strict=True)
        ]
    )
    await reconcile_once(db, fake)
    # −1 (unparsable) never overwrites the status we knew.
    for o, status in zip(orders, (0, 1, 2, 1), strict=True):
        order, row = await load(db, o)
        assert (order.status, row.status) == ("buying", status)


# --- a failed trade --------------------------------------------------------------------------


async def test_declined_offer_returns_money_to_the_balance(
    db: AsyncSession, fake: FakeTradeClient, trade_sent_order: Order
) -> None:
    fake.lookup_returns(
        [trade(project_id=trade_sent_order.id, status=6, reason="Buyer failed to accept")]
    )
    await reconcile_once(db, fake)
    order, row = await load(db, trade_sent_order)
    assert order.status == "returned"
    assert order.refunded_to == "balance"
    assert order.failure_reason == "not_accepted"
    assert row.reason == "Buyer failed to accept"
    assert row.attention_reason is None
    assert await balance(db, order) == PRICE


async def test_an_offer_failed_while_buying_is_returned(
    db: AsyncSession, fake: FakeTradeClient, buying_order: Order
) -> None:
    fake.lookup_returns([trade(project_id=buying_order.id, status=6, reason="Seller canceled")])
    await reconcile_once(db, fake)
    order, _ = await load(db, buying_order)
    assert (order.status, order.failure_reason) == ("returned", "not_accepted")
    assert await balance(db, order) == PRICE


async def test_a_rollback_after_acceptance_is_money_spent(
    db: AsyncSession, fake: FakeTradeClient, trade_sent_order: Order
) -> None:
    # Accepted (release_date) and rolled back between two ticks: no penalties needed. The
    # skin reached the buyer: delivered first, then the attention (ruling P).
    before = attentions("rolled_back")
    fake.lookup_returns([trade(project_id=trade_sent_order.id, status=6, release_date=RELEASE)])
    await reconcile_once(db, fake)
    order, row = await load(db, trade_sent_order)
    assert order.status == "delivered"
    assert order.delivered_at is not None
    assert order.refunded_at is None
    assert row.attention_reason == "rolled_back"
    assert row.accepted_at is not None
    assert attentions("rolled_back") == before + 1
    assert await balance(db, order) == 0


async def test_penalties_alone_mark_a_failed_trade_spent(
    db: AsyncSession, fake: FakeTradeClient, trade_sent_order: Order
) -> None:
    fake.lookup_returns(
        [trade(project_id=trade_sent_order.id, status=6, penalties={"rollback_fee": 200})]
    )
    await reconcile_once(db, fake)
    order, row = await load(db, trade_sent_order)
    assert (order.status, order.refunded_at) == ("delivered", None)
    assert row.attention_reason == "rolled_back"


async def test_a_rollback_seen_while_buying_is_delivered_then_flagged(
    db: AsyncSession, fake: FakeTradeClient, buying_order: Order
) -> None:
    fake.lookup_returns([trade(project_id=buying_order.id, status=6, penalties={"fee": 1})])
    await reconcile_once(db, fake)
    order, row = await load(db, buying_order)
    assert (order.status, order.refunded_at, row.attention_reason) == (
        "delivered",
        None,
        "rolled_back",
    )


async def test_a_rolled_back_attention_is_raised_once_and_a_resolution_stands(
    db: AsyncSession, fake: FakeTradeClient, trade_sent_order: Order
) -> None:
    fake.lookup_returns(
        [trade(project_id=trade_sent_order.id, status=6, penalties={"rollback_fee": 200})]
    )
    before = attentions("rolled_back")
    await reconcile_once(db, fake)
    await set_order(db, trade_sent_order, next_check_at=None)
    await reconcile_once(db, fake)  # delivered now: reconcile no longer follows it
    assert attentions("rolled_back") == before + 1
    assert fake.lookup_calls == 1
    await set_trade(db, trade_sent_order, resolved_at=core_clock.now(), resolved_by="admin:x")
    await watch_once(db, fake)  # out of protection too (our row is 6 now)
    _, row = await load(db, trade_sent_order)
    assert row.resolved_at is not None  # an admin's decision is not re-opened
    assert attentions("rolled_back") == before + 1


async def test_a_refused_attempt_under_the_same_key_is_not_a_rollback(
    db: AsyncSession, fake: FakeTradeClient, trade_sent_order: Order
) -> None:
    refused = trade(
        project_id=trade_sent_order.id, status=6, id=11_111, penalties={"total_penalty": 1}
    )
    ours = trade(project_id=trade_sent_order.id, status=4, release_date=RELEASE)
    fake.lookup_returns([refused, ours])
    await reconcile_once(db, fake)
    order, row = await load(db, trade_sent_order)
    assert order.status == "delivered"
    assert (row.waxpeer_id, row.attention_reason, row.penalties) == (WAXPEER_ID, None, None)


async def test_a_refund_an_open_attention_blocks_waits_for_the_admin(
    db: AsyncSession, fake: FakeTradeClient, trade_sent_order: Order
) -> None:
    await set_trade(db, trade_sent_order, attention_reason="ambiguous_trade")
    fake.lookup_returns([trade(project_id=trade_sent_order.id, status=6)])
    with capture_logs() as logs:
        await reconcile_once(db, fake)
        await set_order(db, trade_sent_order, next_check_at=None)
        await reconcile_once(db, fake)
    held = [e for e in logs if e["event"] == "orders.trade.refund_held"]
    assert len(held) == 1  # warned once, not every tick
    order, _ = await load(db, trade_sent_order)
    assert (order.status, order.refunded_at) == ("trade_sent", None)
    await set_trade(db, trade_sent_order, resolved_at=core_clock.now(), resolved_by="admin:x")
    await set_order(db, trade_sent_order, next_check_at=None)
    await reconcile_once(db, fake)
    order, _ = await load(db, trade_sent_order)
    assert order.status == "returned"


async def test_apply_never_moves_a_settled_order(
    db: AsyncSession, fake: FakeTradeClient, delivered_order: Order
) -> None:
    order, row = await load(db, delivered_order)
    assert await apply(db, order=order, trade=row, wt=trade(project_id=order.id, status=5)) == (
        "unchanged"
    )
    returned = await order_in(db, "returned", status=6)
    order, row = await load(db, returned)
    assert await apply(db, order=order, trade=row, wt=trade(project_id=order.id, status=6)) == (
        "unchanged"
    )
    assert await apply(db, order=order, trade=row, wt=trade(project_id=order.id, status=4)) == (
        "unchanged"
    )
    await db.rollback()


# --- an unconfirmed buy ---------------------------------------------------------------------


async def test_unconfirmed_after_10_min_needs_attention_no_refund(
    db: AsyncSession, fake: FakeTradeClient, clock: Clock, buying_order: Order
) -> None:
    # A lost answer: no Waxpeer id is known (fix round 1: a known one is "missing", not this).
    await set_trade(
        db, buying_order, buy_unconfirmed_at=clock.now(), buy_pending=False, waxpeer_id=None
    )
    fake.lookup_returns([])
    clock.advance(minutes=11)
    await reconcile_once(db, fake)
    order, row = await load(db, buying_order)
    assert row.attention_reason == "buy_unconfirmed"
    assert order.status == "buying"
    assert order.refunded_at is None


async def test_an_unconfirmed_buy_waits_inside_its_window(
    db: AsyncSession, fake: FakeTradeClient, clock: Clock, buying_order: Order
) -> None:
    await set_trade(db, buying_order, buy_unconfirmed_at=clock.now(), waxpeer_id=None)
    fake.lookup_returns([])
    clock.advance(minutes=9)
    await reconcile_once(db, fake)
    order, row = await load(db, buying_order)
    assert (order.status, row.attention_reason) == ("buying", None)
    assert order.next_check_at == clock.now() + timedelta(seconds=10)


async def test_the_unconfirmed_attention_is_raised_once(
    db: AsyncSession, fake: FakeTradeClient, clock: Clock, buying_order: Order
) -> None:
    await set_trade(db, buying_order, buy_unconfirmed_at=clock.now(), waxpeer_id=None)
    fake.lookup_returns([])
    clock.advance(minutes=11)
    before = attentions("buy_unconfirmed")
    await reconcile_once(db, fake)
    clock.advance(seconds=11)
    await reconcile_once(db, fake)
    assert attentions("buy_unconfirmed") == before + 1
    assert fake.lookup_calls == 2


async def test_an_unconfirmed_buy_waxpeer_made_is_adopted_never_rebought(
    db: AsyncSession, fake: FakeTradeClient, buying_order: Order
) -> None:
    await set_trade(
        db, buying_order, waxpeer_id=None, status=None, buy_unconfirmed_at=core_clock.now()
    )
    fake.buy_raises(AssertionError("never buy an unconfirmed order again"))
    fake.lookup_returns([trade(project_id=buying_order.id, status=2, id=70_000_007)])
    await reconcile_once(db, fake)
    order, row = await load(db, buying_order)
    assert (row.waxpeer_id, row.status) == (70_000_007, 2)
    assert row.attention_reason is None
    assert order.status == "buying"
    assert fake.buy_calls == 0


# --- an ambiguous lookup --------------------------------------------------------------------


async def test_two_live_trades_without_our_id_need_attention(
    db: AsyncSession, fake: FakeTradeClient, buying_order: Order
) -> None:
    await set_trade(db, buying_order, waxpeer_id=None)
    before = attentions("ambiguous_trade")
    fake.lookup_returns(
        [
            trade(project_id=buying_order.id, status=2, id=1),
            trade(project_id=buying_order.id, status=4, id=2),
        ]
    )
    await reconcile_once(db, fake)
    order, row = await load(db, buying_order)
    assert row.attention_reason == "ambiguous_trade"
    assert (order.status, order.refunded_at, row.status) == ("buying", None, 0)
    assert attentions("ambiguous_trade") == before + 1


async def test_any_other_refusal_of_the_refund_is_raised(
    db: AsyncSession, fake: FakeTradeClient, trade_sent_order: Order
) -> None:
    await set_order(db, trade_sent_order, paid_with=None)  # a bug: never paid
    order, row = await load(db, trade_sent_order)
    with pytest.raises(ConflictError) as caught:
        await apply(db, order=order, trade=row, wt=trade(project_id=order.id, status=6))
    assert caught.value.extra["code"] == "order_not_paid"
    await db.rollback()
