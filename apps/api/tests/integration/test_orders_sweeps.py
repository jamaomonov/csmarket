"""``orders.sweeps``: which orders each sweep owns, how it treats Waxpeer, and the expiry.

Ported from YuPay's ``test_skins_sweeps.py`` (the fast sweep's ownership, the hourly
protection watch, the daily history audit — an alert there is the attention
``audit_divergence`` and its metric here), plus the reconcile tick's own rules (ruling M:
a pending buy is the buy lease's; ruling K: lookups ≤ 100 ids, nothing locked across
Waxpeer). The unpaid-order expiry is in ``test_orders_expiry.py``.
"""

from __future__ import annotations

from datetime import timedelta

import httpx
import pytest
import respx
from csmarket.core import clock as core_clock
from csmarket.modules.orders import sweeps, trade_audit, trades
from csmarket.modules.orders.models import Order
from csmarket.modules.orders.sweeps import reconcile
from csmarket.modules.skins.api import (
    WaxpeerForbiddenError,
    WaxpeerRateLimitedError,
    WaxpeerTradeClient,
    WaxpeerUnavailableError,
)
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.fake_trade_client import FakeTradeClient
from tests.integration.trade_sweeps_kit import (  # noqa: F401 -- fixtures by name
    RELEASE,
    attentions,
    audit_once,
    buying_order_fixture,
    db_fixture,
    delivered_order_fixture,
    factory,
    fake_fixture,
    load,
    order_in,
    reconcile_once,
    set_order,
    set_trade,
    sweep_settings,
    trade,
    trade_sent_order_fixture,
    watch_once,
)

# --- reconcile: what it owns ---------------------------------------------------------------


async def test_reconcile_follows_only_due_in_flight_orders(
    db: AsyncSession, fake: FakeTradeClient, buying_order: Order, trade_sent_order: Order
) -> None:
    delivered = await order_in(db, "delivered", status=4, release_date=RELEASE)
    later = await order_in(db, "trade_sent", status=4)
    await set_order(db, later, next_check_at=core_clock.now() + timedelta(seconds=5))
    assert await reconcile_once(db, fake) == 2
    (asked,) = fake.asked
    assert sorted(asked) == sorted([buying_order.id, trade_sent_order.id])
    assert delivered.id not in asked
    assert later.id not in asked


async def test_the_next_look_is_ten_seconds_out(
    db: AsyncSession, fake: FakeTradeClient, trade_sent_order: Order
) -> None:
    fake.lookup_returns([trade(project_id=trade_sent_order.id, status=4)])
    await reconcile_once(db, fake)
    order, _ = await load(db, trade_sent_order)
    assert order.next_check_at is not None
    left = order.next_check_at - core_clock.now()
    assert timedelta(seconds=8) < left <= timedelta(seconds=10)
    await reconcile_once(db, fake)
    assert fake.lookup_calls == 1  # not due again yet


async def test_a_tick_asks_waxpeer_at_most_a_hundred_ids(
    db: AsyncSession, fake: FakeTradeClient
) -> None:
    orders = [await order_in(db, "trade_sent", status=4) for _ in range(101)]
    assert await reconcile_once(db, fake) == 100
    assert await reconcile_once(db, fake) == 1
    assert [len(batch) for batch in fake.asked] == [100, 1]
    assert {i for batch in fake.asked for i in batch} == {o.id for o in orders}


@pytest.mark.parametrize(
    "error",
    [
        WaxpeerUnavailableError("down"),
        WaxpeerRateLimitedError("slow down", retry_after_seconds=None),
        WaxpeerForbiddenError("ip"),
    ],
)
async def test_a_failed_lookup_leaves_every_order_due(
    db: AsyncSession, fake: FakeTradeClient, trade_sent_order: Order, error: Exception
) -> None:
    fake.lookup_raises(error)
    assert await reconcile_once(db, fake) == 1
    order, row = await load(db, trade_sent_order)
    assert (order.status, order.next_check_at, row.last_polled_at) == ("trade_sent", None, None)


async def test_a_pending_buy_goes_through_the_buy_and_its_lease(
    db: AsyncSession, fake: FakeTradeClient
) -> None:
    pending = await order_in(db, "buying", waxpeer_id=None, status=None, buy_pending=True)
    leased = await order_in(db, "buying", waxpeer_id=None, status=None, buy_pending=True)
    lease = core_clock.now() + timedelta(minutes=4)
    await set_order(db, leased, next_check_at=lease)
    assert await reconcile_once(db, fake) == 1
    assert [p for _, _, p in fake.bought] == [pending.id]
    order, row = await load(db, pending)
    assert (order.status, row.buy_pending, row.status) == ("buying", False, 0)
    assert order.next_check_at is not None
    assert order.next_check_at <= core_clock.now()  # released by the buy, not +10 s
    order, row = await load(db, leased)
    assert (order.next_check_at, row.buy_pending) == (lease, True)  # never touched


async def test_a_buy_pending_row_is_never_rescheduled_by_the_poll(
    db: AsyncSession, fake: FakeTradeClient, trade_sent_order: Order
) -> None:
    # Read as polled, then the row turns buy_pending before the lock (re-checked under it).
    async def turn_pending() -> None:
        await set_trade(db, trade_sent_order, buy_pending=True)

    fake.before_lookup = turn_pending
    fake.lookup_returns([trade(project_id=trade_sent_order.id, status=4, release_date=RELEASE)])
    await reconcile_once(db, fake)
    order, _ = await load(db, trade_sent_order)
    assert (order.status, order.next_check_at) == ("trade_sent", None)


async def test_one_bad_order_does_not_stop_the_tick(
    db: AsyncSession,
    fake: FakeTradeClient,
    trade_sent_order: Order,
    buying_order: Order,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_apply = trades.apply

    async def flaky(db: AsyncSession, *, order: Order, trade: object, wt: object) -> str:
        if order.id == trade_sent_order.id:
            raise RuntimeError("boom")
        return await real_apply(db, order=order, trade=trade, wt=wt)  # type: ignore[arg-type]

    monkeypatch.setattr(sweeps, "apply", flaky)
    fake.lookup_returns(
        [
            trade(project_id=trade_sent_order.id, status=4, release_date=RELEASE),
            trade(project_id=buying_order.id, status=4),
        ]
    )
    assert await reconcile_once(db, fake) == 2
    bad, _ = await load(db, trade_sent_order)
    good, _ = await load(db, buying_order)
    assert (bad.status, bad.next_check_at) == ("trade_sent", None)  # retried next tick
    assert good.status == "trade_sent"


async def test_a_crashing_buy_does_not_stop_the_tick(
    db: AsyncSession, fake: FakeTradeClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    await order_in(db, "buying", waxpeer_id=None, status=None, buy_pending=True)
    monkeypatch.setattr(sweeps, "attempt_buy", _raises)
    assert await reconcile_once(db, fake) == 1


async def _raises(*_: object, **__: object) -> str:
    raise RuntimeError("boom")


async def test_reconcile_never_raises(fake: FakeTradeClient) -> None:
    def broken() -> AsyncSession:
        raise RuntimeError("no database")

    assert await reconcile(broken, fake, settings=sweep_settings()) == 0


@respx.mock
async def test_the_sweep_delivers_an_accepted_skin_end_to_end(
    db: AsyncSession, trade_sent_order: Order
) -> None:
    base = "https://api.waxpeer.test/v1"
    body = {
        "id": 60_000_001,
        "project_id": trade_sent_order.id,
        "status": 4,
        "trade_id": "7700112233",
        "done": False,
        "release_date": "2026-10-09T12:00:00.000Z",
        "is_released": False,
        "price": 12_345,
    }
    respx.get(f"{base}/check-many-project-id").mock(
        return_value=httpx.Response(200, json={"success": True, "trades": [body]})
    )
    client = WaxpeerTradeClient(api_key="test-key-not-real", base_url=base, timeout_seconds=1)
    await reconcile(factory(db), client, settings=sweep_settings())
    order, row = await load(db, trade_sent_order)
    assert order.status == "delivered"
    assert row.release_date == RELEASE


# --- the protection watch ------------------------------------------------------------------


async def test_a_released_trade_is_marked_released(
    db: AsyncSession, fake: FakeTradeClient, delivered_order: Order
) -> None:
    fake.lookup_returns(
        [trade(project_id=delivered_order.id, status=5, release_date=RELEASE, is_released=True)]
    )
    assert await watch_once(db, fake) == 1
    order, row = await load(db, delivered_order)
    assert (row.status, row.is_released, row.attention_reason) == (5, True, None)
    assert order.status == "delivered"
    assert await watch_once(db, fake) == 0  # out of protection: no longer watched


async def test_rollback_after_accept_keeps_money_spent(
    db: AsyncSession, fake: FakeTradeClient, delivered_order: Order
) -> None:
    before = attentions("rolled_back")
    fake.lookup_returns(
        [trade(project_id=delivered_order.id, status=6, penalties={"rollback_fee": 200})]
    )
    await watch_once(db, fake)
    order, row = await load(db, delivered_order)
    assert order.status == "delivered"
    assert order.refunded_at is None
    assert row.attention_reason == "rolled_back"
    assert row.penalties == {"rollback_fee": 200}
    assert attentions("rolled_back") == before + 1


async def test_the_watch_reads_our_trade_not_a_refused_attempt(
    db: AsyncSession, fake: FakeTradeClient, delivered_order: Order
) -> None:
    refused = trade(project_id=delivered_order.id, status=6, id=999, penalties={"x": 1})
    ours = trade(project_id=delivered_order.id, status=5, release_date=RELEASE, is_released=True)
    fake.lookup_returns([refused, ours])
    await watch_once(db, fake)
    _, row = await load(db, delivered_order)
    assert (row.status, row.is_released, row.attention_reason) == (5, True, None)


async def test_the_watch_skips_a_trade_it_cannot_tell_apart(
    db: AsyncSession, fake: FakeTradeClient, delivered_order: Order
) -> None:
    await set_trade(db, delivered_order, waxpeer_id=None)
    fake.lookup_returns(
        [
            trade(project_id=delivered_order.id, status=4, id=1),
            trade(project_id=delivered_order.id, status=4, id=2),
        ]
    )
    await watch_once(db, fake)
    _, row = await load(db, delivered_order)
    assert (row.status, row.is_released, row.last_polled_at) == (4, False, None)


async def test_the_watch_asks_in_batches_and_stops_on_a_failure(
    db: AsyncSession, fake: FakeTradeClient
) -> None:
    for _ in range(101):
        await order_in(db, "delivered", status=4, release_date=RELEASE)
    assert await watch_once(db, fake) == 101
    assert [len(batch) for batch in fake.asked] == [100, 1]
    fake.lookup_raises(WaxpeerUnavailableError("down"))
    assert await watch_once(db, fake) == 101
    assert fake.lookup_calls == 3  # the first batch failed, the second was not asked


async def test_one_bad_trade_does_not_stop_the_watch(
    db: AsyncSession,
    fake: FakeTradeClient,
    delivered_order: Order,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    other = await order_in(db, "delivered", status=4, release_date=RELEASE)
    real_apply = trades.apply

    async def flaky(db: AsyncSession, *, order: Order, trade: object, wt: object) -> str:
        if order.id == delivered_order.id:
            raise RuntimeError("boom")
        return await real_apply(db, order=order, trade=trade, wt=wt)  # type: ignore[arg-type]

    monkeypatch.setattr(sweeps, "apply", flaky)
    fake.lookup_returns(
        [
            trade(project_id=delivered_order.id, status=5, is_released=True),
            trade(project_id=other.id, status=5, is_released=True),
        ]
    )
    await watch_once(db, fake)
    _, row = await load(db, other)
    assert row.is_released is True


# --- the history audit ---------------------------------------------------------------------


async def _released(db: AsyncSession) -> Order:
    return await order_in(db, "delivered", status=5, release_date=RELEASE, is_released=True)


async def _refunded(db: AsyncSession, *, status: int | None = 6) -> Order:
    order = await order_in(db, "returned", status=status)
    await set_order(db, order, refunded_at=core_clock.now(), refunded_to="balance")
    return order


async def test_the_audit_is_silent_when_waxpeer_agrees(
    db: AsyncSession, fake: FakeTradeClient, buying_order: Order
) -> None:
    released, declined = await _released(db), await _refunded(db)
    fake.lookup_returns(
        [
            trade(project_id=released.id, status=5, is_released=True),
            trade(project_id=declined.id, status=6),
        ]
    )
    before = attentions("audit_divergence")
    assert await audit_once(db, fake) == 0
    assert attentions("audit_divergence") == before
    asked = [pid for batch in fake.asked for pid in batch]
    assert buying_order.id not in asked  # in flight: the reconcile sweep's


async def test_a_released_trade_rolled_back_later_is_flagged(
    db: AsyncSession, fake: FakeTradeClient
) -> None:
    order0 = await _released(db)
    fake.lookup_returns([trade(project_id=order0.id, status=6, penalties={"total": 1500})])
    before = attentions("audit_divergence")
    assert await audit_once(db, fake) == 1
    order, row = await load(db, order0)
    assert (row.audit_verdict, row.attention_reason) == ("rolled_back", "audit_divergence")
    assert (order.status, row.status) == ("delivered", 5)  # the audit changes no trade state
    assert attentions("audit_divergence") == before + 1


async def test_a_refunded_trade_that_was_delivered_is_flagged(
    db: AsyncSession, fake: FakeTradeClient
) -> None:
    order0 = await _refunded(db)
    fake.lookup_returns([trade(project_id=order0.id, status=5)])
    assert await audit_once(db, fake) == 1
    _, row = await load(db, order0)
    assert row.audit_verdict == "delivered_refunded"


async def test_a_trade_waxpeer_does_not_know_is_flagged(
    db: AsyncSession, fake: FakeTradeClient
) -> None:
    seen = await _released(db)
    sold_out = await _refunded(db, status=None)  # never reached Waxpeer: fine
    assert await audit_once(db, fake) == 1
    _, row = await load(db, seen)
    assert row.audit_verdict == "unknown"
    _, row = await load(db, sold_out)
    assert (row.audit_verdict, row.attention_reason) == (None, None)


async def test_the_audit_asks_in_batches_of_a_hundred(
    db: AsyncSession, fake: FakeTradeClient
) -> None:
    orders = [await _released(db) for _ in range(101)]
    fake.lookup_returns([trade(project_id=o.id, status=5, is_released=True) for o in orders])
    assert await audit_once(db, fake) == 0
    assert [len(batch) for batch in fake.asked] == [100, 1]


async def test_the_audit_skips_trades_older_than_the_window(
    db: AsyncSession, fake: FakeTradeClient
) -> None:
    old = await _released(db)
    await set_trade(db, old, created_at=core_clock.now() - timedelta(days=20))
    assert await audit_once(db, fake) == 0
    assert fake.asked == []


async def test_an_unreachable_waxpeer_never_flags(db: AsyncSession, fake: FakeTradeClient) -> None:
    order0 = await _released(db)
    fake.lookup_raises(WaxpeerUnavailableError("down"))
    before = attentions("audit_divergence")
    assert await audit_once(db, fake) == 0
    _, row = await load(db, order0)
    assert (row.audit_verdict, row.attention_reason) == (None, None)
    assert attentions("audit_divergence") == before


async def test_a_divergence_is_flagged_once_not_every_night(
    db: AsyncSession, fake: FakeTradeClient
) -> None:
    order0 = await _released(db)
    fake.lookup_returns([trade(project_id=order0.id, status=6)])
    before = attentions("audit_divergence")
    assert await audit_once(db, fake) == 1
    assert await audit_once(db, fake) == 0
    assert attentions("audit_divergence") == before + 1
    _, row = await load(db, order0)
    assert row.audit_verdict == "rolled_back"


async def test_a_changed_divergence_is_flagged_again(
    db: AsyncSession, fake: FakeTradeClient
) -> None:
    order0 = await _released(db)
    fake.lookup_returns([trade(project_id=order0.id, status=6)])
    await audit_once(db, fake)
    await set_trade(db, order0, resolved_at=core_clock.now(), resolved_by="admin:x")
    before = attentions("audit_divergence")
    fake.lookup_returns([])
    assert await audit_once(db, fake) == 1
    assert attentions("audit_divergence") == before + 1
    _, row = await load(db, order0)
    assert (row.audit_verdict, row.attention_reason, row.resolved_at) == (
        "unknown",
        "audit_divergence",
        None,  # a new verdict re-opens the attention
    )


async def test_a_new_verdict_alerts_even_while_the_attention_is_open(
    db: AsyncSession, fake: FakeTradeClient
) -> None:
    order0 = await _released(db)
    fake.lookup_returns([trade(project_id=order0.id, status=6)])
    await audit_once(db, fake)
    before = attentions("audit_divergence")
    fake.lookup_returns([])
    assert await audit_once(db, fake) == 1
    assert attentions("audit_divergence") == before + 1


async def test_agreement_clears_the_verdict(db: AsyncSession, fake: FakeTradeClient) -> None:
    order0 = await _released(db)
    fake.lookup_returns([trade(project_id=order0.id, status=6)])
    await audit_once(db, fake)
    fake.lookup_returns([trade(project_id=order0.id, status=5, is_released=True)])
    assert await audit_once(db, fake) == 0
    _, row = await load(db, order0)
    assert row.audit_verdict is None
    assert row.attention_reason == "audit_divergence"  # an admin resolves it


async def test_one_failed_row_does_not_stop_the_audit(
    db: AsyncSession, fake: FakeTradeClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    first, second = await _released(db), await _released(db)
    real = trade_audit._verdict
    calls: list[str] = []

    def flaky(order: Order, trade: object, theirs: object) -> str | None:
        calls.append(order.id)
        if len(calls) == 1:
            raise RuntimeError("boom")
        return real(order, trade, theirs)  # type: ignore[arg-type]

    monkeypatch.setattr(trade_audit, "_verdict", flaky)
    fake.lookup_returns(
        [trade(project_id=first.id, status=6), trade(project_id=second.id, status=6)]
    )
    assert await audit_once(db, fake) == 1
    verdicts = sorted([(await load(db, o))[1].audit_verdict for o in (first, second)], key=str)
    assert verdicts == [None, "rolled_back"]  # the failed one is tried again tomorrow


async def test_the_audit_flags_several_live_trades_under_one_key(
    db: AsyncSession, fake: FakeTradeClient
) -> None:
    order0 = await _released(db)
    await set_trade(db, order0, waxpeer_id=None)
    fake.lookup_returns(
        [trade(project_id=order0.id, status=4, id=1), trade(project_id=order0.id, status=4, id=2)]
    )
    assert await audit_once(db, fake) == 1
    _, row = await load(db, order0)
    assert row.audit_verdict == "ambiguous"


async def test_a_rollback_the_watch_already_flagged_is_not_flagged_again(
    db: AsyncSession, fake: FakeTradeClient, delivered_order: Order
) -> None:
    fake.lookup_returns([trade(project_id=delivered_order.id, status=6, penalties={"x": 1})])
    await watch_once(db, fake)
    assert await audit_once(db, fake) == 0
    _, row = await load(db, delivered_order)
    assert (row.audit_verdict, row.attention_reason) == (None, "rolled_back")
