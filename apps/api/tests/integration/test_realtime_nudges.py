"""Every order status change nudges its owner once, on commit (M4b T2, rulings R1, R4)."""

from __future__ import annotations

from datetime import timedelta

import pytest
from csmarket.core import clock as core_clock
from csmarket.modules.orders.buying import drain_paid
from csmarket.modules.orders.expiry import expire_pending
from csmarket.modules.orders.models import Order
from csmarket.modules.orders.paid import mark_paid
from csmarket.modules.orders.refunds import refund_to_balance
from csmarket.modules.realtime.api import CHANNEL, nudge
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.fake_trade_client import FakeTradeClient
from tests.integration.orders_factory import listen_channel, make_order
from tests.integration.trade_sweeps_kit import (  # noqa: F401 -- fixtures
    buying_order_fixture,
    clock_fixture,
    db_fixture,
    fake_fixture,
    reconcile_once,
    set_trade,
    trade,
    trade_sent_order_fixture,
)


def _payload(order: Order) -> str:
    return f"{order.user_id}:{order.number}"


async def test_nudge_is_delivered_only_after_commit(db: AsyncSession) -> None:
    order = await make_order(db, status="pending")
    async with listen_channel(CHANNEL) as events:
        await nudge(db, user_id=order.user_id, number=order.number)
        assert await events.drain() == []
        await db.commit()
        assert await events.drain() == [_payload(order)]


async def test_paid_nudges(db: AsyncSession) -> None:
    order = await make_order(db, status="pending")
    async with listen_channel(CHANNEL) as events:
        locked = await db.get(Order, order.id, with_for_update=True)
        assert locked is not None
        await mark_paid(db, locked, provider="wallet")
        await db.commit()
        assert await events.drain() == [_payload(order)]


async def test_claim_nudges(db: AsyncSession, fake: FakeTradeClient) -> None:
    order = await make_order(db, status="paid", paid_at=core_clock.now())
    fake.lookup_returns([])
    fake.buy_raises(RuntimeError("not reached in this test"))
    async with listen_channel(CHANNEL) as events:
        await drain_paid(db, client=fake, limit=1)
        assert _payload(order) in await events.drain()


@pytest.mark.parametrize(
    ("status", "release", "expected"),
    [(4, None, 1), (4, "2026-10-09T00:00:00Z", 1), (0, None, 0)],
    ids=["trade_sent", "delivered", "unchanged"],
)
async def test_reconcile_nudges_only_on_a_change(  # noqa: PLR0917 -- fixtures + parameters
    db: AsyncSession,
    fake: FakeTradeClient,
    buying_order: Order,
    status: int,
    release: str | None,
    expected: int,
) -> None:
    waxpeer_id = 70_000_001
    await set_trade(db, buying_order, waxpeer_id=waxpeer_id, buy_pending=False)
    over = {"release_date": release} if release else {}
    fake.lookup_returns([trade(project_id=buying_order.id, status=status, id=waxpeer_id, **over)])
    async with listen_channel(CHANNEL) as events:
        await reconcile_once(db, fake)
        assert (await events.drain()).count(_payload(buying_order)) == expected


async def test_refund_nudges_once(db: AsyncSession) -> None:
    order = await make_order(db, status="buying", paid_with="wallet", paid_at=core_clock.now())
    async with listen_channel(CHANNEL) as events:
        locked = await db.get(Order, order.id, with_for_update=True)
        assert locked is not None
        assert await refund_to_balance(
            db, order=locked, to_status="failed", reason="sold_out", actor="orders"
        )
        assert not await refund_to_balance(
            db, order=locked, to_status="failed", reason="sold_out", actor="orders"
        )
        await db.commit()
        assert await events.drain() == [_payload(order)]


async def test_expiry_nudges(db: AsyncSession) -> None:
    order = await make_order(
        db, status="pending", expires_at=core_clock.now() - timedelta(minutes=1)
    )
    async with listen_channel(CHANNEL) as events:
        assert await expire_pending(db) == 1
        await db.commit()
        assert await events.drain() == [_payload(order)]
