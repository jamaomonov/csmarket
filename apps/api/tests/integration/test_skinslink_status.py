"""Skinslink statuses onto orders (spec 2026-10-06 §6): ``trade_sent``, ``delivered``,
refunds, a rollback; the one-shot check drain and the reconcile."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from csmarket.core import clock
from csmarket.core.config import Settings, get_settings
from csmarket.modules.orders.models import Order
from csmarket.modules.orders.skinslink_buying import attempt_skinslink_buy
from csmarket.modules.orders.skinslink_reconcile import reconcile_skinslink
from csmarket.modules.orders.skinslink_status import check_purchase, drain_checks
from csmarket.modules.orders.trade_view import skin_trade_out
from csmarket.modules.skinslink.api import Purchase
from csmarket.modules.skinslink.checks import enqueue_check
from csmarket.modules.skinslink.models import SkinslinkPurchase
from csmarket.modules.wallet.api import user_balance
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from tests.integration.fake_skinslink_client import FakeSkinslinkClient, purchase
from tests.integration.skinslink_factory import OFFER, PRICE, PURCHASE_ID, make_skinslink_order

pytestmark = pytest.mark.asyncio


async def _fresh(db: AsyncSession, order: Order) -> tuple[Order, SkinslinkPurchase]:
    row = await db.scalar(
        select(Order).where(Order.id == order.id).execution_options(populate_existing=True)
    )
    p = await db.scalar(
        select(SkinslinkPurchase)
        .where(SkinslinkPurchase.order_id == order.id)
        .execution_options(populate_existing=True)
    )
    assert row is not None
    assert p is not None
    return row, p


async def _check(db: AsyncSession, order: Order, report: Purchase | None) -> str:
    return await check_purchase(
        db, FakeSkinslinkClient(statuses={order.id: report}), order_id=order.id
    )


async def test_active_on_a_buying_order_sends_the_trade(db_session: AsyncSession) -> None:
    order, _ = await make_skinslink_order(
        db_session, status="buying", purchase_status="pending", offer_id=None
    )
    assert await _check(db_session, order, purchase("active", offer_id=OFFER)) == "trade_sent"
    assert (await _fresh(db_session, order))[0].status == "trade_sent"


async def test_completed_delivers(db_session: AsyncSession) -> None:
    order, _ = await make_skinslink_order(db_session)
    assert await _check(db_session, order, purchase("completed", offer_id=OFFER)) == "delivered"
    row, p = await _fresh(db_session, order)
    assert (row.status, p.status) == ("delivered", "completed")
    assert row.delivered_at is not None


async def test_hold_keeps_trade_sent_and_records_the_end(db_session: AsyncSession) -> None:
    order, _ = await make_skinslink_order(db_session)
    report = purchase("hold", offer_id=OFFER, hold_end_date="2026-10-13T00:00:00Z")
    assert await _check(db_session, order, report) == "unchanged"
    row, p = await _fresh(db_session, order)
    assert row.status == "trade_sent"
    assert p.hold_end_date is not None


@pytest.mark.parametrize("status", ["failed", "canceled"])
async def test_a_declined_offer_returns_the_money(db_session: AsyncSession, status: str) -> None:
    order, _ = await make_skinslink_order(db_session)
    assert await _check(db_session, order, purchase(status)) == "returned"
    row, _ = await _fresh(db_session, order)
    assert (row.status, row.failure_reason, row.refunded_to) == (
        "returned",
        "not_accepted",
        "balance",
    )
    assert await user_balance(db_session, order.user_id) == PRICE


@pytest.mark.parametrize(
    ("fail_reason", "reason"),
    [
        ("insufficient_balance", "source_low_balance"),
        ("trade_banned", "invalid_trade_link"),
        ("hold", "trade_hold"),
        ("hold_and_permissions", "trade_hold"),
        ("permissions", "invalid_trade_link"),
        ("item_sold", "sold_out"),
        (None, "sold_out"),
    ],
)
async def test_a_failed_purchase_before_any_offer_is_refunded_by_its_reason(
    db_session: AsyncSession, fail_reason: str | None, reason: str
) -> None:
    order, _ = await make_skinslink_order(
        db_session, status="buying", purchase_status="pending", offer_id=None
    )
    assert await _check(db_session, order, purchase("failed", fail_reason=fail_reason)) == "failed"
    row, _ = await _fresh(db_session, order)
    assert (row.status, row.failure_reason) == ("failed", reason)


async def test_reverted_after_delivery_is_attention_not_a_refund(db_session: AsyncSession) -> None:
    order, _ = await make_skinslink_order(db_session)
    await _check(db_session, order, purchase("completed", offer_id=OFFER))
    reverted = purchase("reverted", fail_reason="user_reverted")
    assert await _check(db_session, order, reverted) == "rolled_back"
    row, p = await _fresh(db_session, order)
    assert (row.status, p.attention_reason) == ("delivered", "rolled_back")
    assert await user_balance(db_session, order.user_id) == Decimal(0)
    assert await _check(db_session, order, reverted) == "rolled_back"  # once, not every tick


async def test_reverted_before_delivery_returns_the_money(db_session: AsyncSession) -> None:
    order, _ = await make_skinslink_order(db_session)
    assert await _check(db_session, order, purchase("reverted")) == "returned"
    assert await user_balance(db_session, order.user_id) == PRICE


async def test_an_open_attention_holds_the_refund(db_session: AsyncSession) -> None:
    order, _ = await make_skinslink_order(db_session, attention_reason="buy_unconfirmed")
    assert await _check(db_session, order, purchase("canceled")) == "held"
    assert (await _fresh(db_session, order))[0].status == "trade_sent"


async def test_new_and_pending_change_nothing(db_session: AsyncSession) -> None:
    order, _ = await make_skinslink_order(
        db_session, status="buying", purchase_status="pending", offer_id=None
    )
    assert await _check(db_session, order, purchase("pending")) == "unchanged"
    assert (await _fresh(db_session, order))[0].status == "buying"


async def test_a_pending_buy_is_left_to_the_buy_path(db_session: AsyncSession) -> None:
    order, _ = await make_skinslink_order(
        db_session,
        status="buying",
        purchase_id=None,
        purchase_status=None,
        offer_id=None,
        buy_pending=True,
    )
    assert await _check(db_session, order, purchase("failed")) == "unchanged"
    assert (await _fresh(db_session, order))[0].status == "buying"


async def test_an_unconfirmed_buy_skinslink_never_saw_is_repeated_after_the_wait(
    db_session: AsyncSession,
) -> None:
    minutes = get_settings().order_unconfirmed_minutes
    order, _ = await make_skinslink_order(
        db_session,
        status="buying",
        purchase_id=None,
        purchase_status=None,
        offer_id=None,
        buy_unconfirmed_at=clock.now() - timedelta(minutes=minutes + 1),
    )
    assert await _check(db_session, order, None) == "repeat"
    row, p = await _fresh(db_session, order)
    # Never refunded on a silence: the same merchant_tx_id is sent again, and Skinslink
    # answers it with the stored purchase, a new one, or a refusal.
    assert (row.status, row.refunded_at) == ("buying", None)
    assert (p.buy_pending, p.buy_unconfirmed_at) == (True, None)
    fake = FakeSkinslinkClient(purchase("active", offer_id=OFFER))
    assert await attempt_skinslink_buy(db_session, fake, order_id=order.id) == "bought"
    assert fake.calls[0]["merchant_tx_id"] == order.id
    assert (await _fresh(db_session, order))[0].status == "trade_sent"


async def test_an_unconfirmed_buy_is_adopted_when_skinslink_has_it(
    db_session: AsyncSession,
) -> None:
    order, _ = await make_skinslink_order(
        db_session,
        status="buying",
        purchase_id=None,
        purchase_status=None,
        offer_id=None,
        buy_unconfirmed_at=clock.now(),
    )
    assert await _check(db_session, order, purchase("active", offer_id=OFFER)) == "trade_sent"
    row, p = await _fresh(db_session, order)
    assert (row.status, p.purchase_id, p.buy_unconfirmed_at) == ("trade_sent", 178, None)


async def test_a_fresh_unconfirmed_buy_waits(db_session: AsyncSession) -> None:
    order, _ = await make_skinslink_order(
        db_session,
        status="buying",
        purchase_id=None,
        purchase_status=None,
        offer_id=None,
        buy_unconfirmed_at=clock.now(),
    )
    assert await _check(db_session, order, None) == "unchanged"


async def test_the_buyer_view_of_a_skinslink_order(db_session: AsyncSession) -> None:
    order, p = await make_skinslink_order(db_session)
    view = skin_trade_out(order, None, purchase=p)
    assert view is not None
    assert view.state == "offer_sent"
    assert view.offer_url == f"https://steamcommunity.com/tradeoffer/{OFFER}/"
    assert (view.seller, view.release_date, view.send_until) == (None, None, None)


async def test_the_check_drain_asks_skinslink_and_applies(db_session: AsyncSession) -> None:
    order, _ = await make_skinslink_order(db_session)
    await enqueue_check(db_session, PURCHASE_ID)
    await db_session.commit()
    fake = FakeSkinslinkClient(statuses={order.id: purchase("completed", offer_id=OFFER)})
    assert await drain_checks(db_session, client=fake) == 1
    assert (await _fresh(db_session, order))[0].status == "delivered"
    assert await drain_checks(db_session, client=fake) == 0  # one-shot rows are gone


async def test_a_check_for_an_unknown_purchase_is_dropped(db_session: AsyncSession) -> None:
    await enqueue_check(db_session, 999)
    await db_session.commit()
    fake = FakeSkinslinkClient()
    assert await drain_checks(db_session, client=fake) == 1
    assert fake.status_calls == []


async def test_reconcile_polls_open_purchases_and_buys_pending_ones(
    db_engine: AsyncEngine, db_session: AsyncSession
) -> None:
    settings: Settings = get_settings().model_copy(
        update={"skinslink_enabled": True, "skinslink_api_key": "k", "skinslink_secret": "s"}
    )
    sent, _ = await make_skinslink_order(db_session)
    pending, _ = await make_skinslink_order(
        db_session,
        status="buying",
        purchase_id=None,
        purchase_status=None,
        offer_id=None,
        buy_pending=True,
    )
    done, _ = await make_skinslink_order(db_session, status="delivered", purchase_id=180)
    fake = FakeSkinslinkClient(
        purchase("pending", id=181), statuses={sent.id: purchase("completed", offer_id=OFFER)}
    )
    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    assert await reconcile_skinslink(factory, fake, settings=settings) == 2
    assert (await _fresh(db_session, sent))[0].status == "delivered"
    assert (await _fresh(db_session, pending))[1].purchase_id == 181
    assert fake.status_calls == [sent.id]
    assert (await _fresh(db_session, done))[0].status == "delivered"


async def test_a_held_trade_reads_accepted_until_the_hold_ends(db_session: AsyncSession) -> None:
    order, _ = await make_skinslink_order(db_session)
    report = purchase("hold", offer_id=OFFER, hold_end_date="2026-10-13T00:00:00Z")
    await _check(db_session, order, report)
    row, p = await _fresh(db_session, order)
    view = skin_trade_out(row, None, purchase=p)
    assert view is not None
    assert view.state == "accepted"
    assert view.release_date == p.hold_end_date
    assert view.release_date is not None


async def test_a_held_trade_is_polled_every_ten_minutes_not_every_tick(
    db_engine: AsyncEngine, db_session: AsyncSession
) -> None:
    settings: Settings = get_settings().model_copy(
        update={"skinslink_enabled": True, "skinslink_api_key": "k", "skinslink_secret": "s"}
    )
    ends = clock.now() + timedelta(days=6)
    fresh, _ = await make_skinslink_order(
        db_session,
        purchase_status="hold",
        hold_end_date=ends,
        last_polled_at=clock.now() - timedelta(minutes=1),
    )
    due, _ = await make_skinslink_order(
        db_session,
        purchase_status="hold",
        hold_end_date=ends,
        purchase_id=179,
        last_polled_at=clock.now() - timedelta(minutes=11),
    )
    over, _ = await make_skinslink_order(
        db_session,
        purchase_status="hold",
        purchase_id=180,
        hold_end_date=clock.now() - timedelta(minutes=1),
        last_polled_at=clock.now() - timedelta(minutes=1),
    )
    fake = FakeSkinslinkClient()
    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    await reconcile_skinslink(factory, fake, settings=settings)
    assert sorted(fake.status_calls) == sorted([due.id, over.id])
    assert fresh.id not in fake.status_calls
