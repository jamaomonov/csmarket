"""``orders.sweeps.expire_pending``: unpaid orders past ``expires_at`` are cancelled, unless
a kassa holds their attempt (M3 R8: the kassa's own timeout releases it first).
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from csmarket.core import clock as core_clock
from csmarket.modules.orders.models import Order
from csmarket.modules.orders.sweeps import expire_pending
from csmarket.modules.payments.hooks import ensure_attempt, mark_pending
from csmarket.modules.payments.models import Payment
from csmarket.modules.payments.payable import resolve
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.orders_factory import make_order
from tests.integration.trade_sweeps_kit import db_fixture, factory  # noqa: F401 -- fixture


@pytest.fixture
async def expired(db: AsyncSession) -> Order:
    return await make_order(db, expires_at=core_clock.now() - timedelta(seconds=1))


async def _attempt(db: AsyncSession, order: Order, *, hold: bool) -> Payment:
    """A kassa attempt: ``created`` (a pay call), or ``pending`` (a kassa holds it)."""
    attempt = await ensure_attempt(
        db, payable=await resolve(db, order.number, lock=True), provider="click"
    )
    if hold:
        await mark_pending(db, payment=attempt)
    await db.commit()
    return attempt


async def _status(db: AsyncSession, model: type[Order] | type[Payment], row_id: str) -> str:
    status = await db.scalar(select(model.status).where(model.id == row_id))
    assert status is not None
    return status


async def _expire(db: AsyncSession) -> int:
    count = await expire_pending(db)
    await db.commit()
    return count


async def test_an_unpaid_order_past_its_time_is_cancelled(db: AsyncSession, expired: Order) -> None:
    fresh = await make_order(db)
    assert await _expire(db) == 1
    assert await _status(db, Order, expired.id) == "cancelled"
    assert await _status(db, Order, fresh.id) == "pending"
    (order,) = (await db.execute(select(Order).where(Order.id == expired.id))).scalars()
    assert order.cancelled_at is not None


async def test_expiry_cancels_the_attempts_no_kassa_took_up(
    db: AsyncSession, expired: Order
) -> None:
    attempt = await _attempt(db, expired, hold=False)
    assert await _expire(db) == 1
    assert await _status(db, Order, expired.id) == "cancelled"
    assert await _status(db, Payment, attempt.id) == "cancelled"


async def test_expiry_keeps_an_order_a_kassa_holds(db: AsyncSession, expired: Order) -> None:
    attempt = await _attempt(db, expired, hold=True)
    assert await _expire(db) == 0
    assert await _status(db, Order, expired.id) == "pending"
    assert await _status(db, Payment, attempt.id) == "pending"


async def test_expiry_leaves_paid_and_in_flight_orders(db: AsyncSession) -> None:
    past = core_clock.now() - timedelta(minutes=1)
    paid = await make_order(db, status="paid", paid_with="payme", expires_at=past)
    assert await _expire(db) == 0
    assert await _status(db, Order, paid.id) == "paid"


async def test_expiry_skips_an_order_another_session_holds(
    db: AsyncSession, expired: Order
) -> None:
    async with _Holding(db, expired) as _:
        assert await _expire(db) == 0
    assert await _expire(db) == 1


async def test_expiry_works_in_bounded_batches(db: AsyncSession) -> None:
    past = core_clock.now() - timedelta(minutes=1)
    for _ in range(3):
        await make_order(db, expires_at=past)
    assert await expire_pending(db, batch=2) == 2
    await db.commit()
    assert await _expire(db) == 1


class _Holding:
    """Hold ``order`` ``FOR UPDATE`` on a second connection for the ``async with`` block."""

    def __init__(self, db: AsyncSession, order: Order) -> None:
        self._session = factory(db)()
        self._order = order

    async def __aenter__(self) -> AsyncSession:
        await self._session.execute(
            select(Order).where(Order.id == self._order.id).with_for_update()
        )
        return self._session

    async def __aexit__(self, *_: object) -> None:
        await self._session.rollback()
        await self._session.close()
