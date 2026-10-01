"""Provider hooks for orders (M4a): an order is paid once, notifies the worker once, and a
kassa can never reverse it (ruling R7)."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from decimal import Decimal

import pytest
from csmarket.core import clock
from csmarket.modules.orders.models import Order
from csmarket.modules.payments.hooks import (
    AlreadyPaidError,
    OrderReversalRefusedError,
    ReversalRefusedError,
    TopupSpentError,
    cancel_pending,
    ensure_attempt,
    mark_pending,
    reverse,
    settle,
)
from csmarket.modules.payments.models import Payment
from csmarket.modules.payments.payable import resolve
from csmarket.modules.wallet.api import user_balance
from csmarket.modules.wallet.models import WalletTransaction
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from tests.integration.orders_factory import listen_orders, make_order

PRICE = Decimal(171_800)


async def _attempt(db: AsyncSession, provider: str = "payme") -> tuple[Order, Payment]:
    order = await make_order(db, price_uzs=PRICE)
    payment = await ensure_attempt(
        db, payable=await resolve(db, order.number, lock=True), provider=provider
    )
    await db.commit()
    return order, payment


async def _order(db: AsyncSession, order_id: str) -> Order:
    stmt = select(Order).where(Order.id == order_id).execution_options(populate_existing=True)
    return (await db.execute(stmt)).scalar_one()


async def test_an_order_attempt_is_created_and_reused(db_session: AsyncSession) -> None:
    order, a = await _attempt(db_session)
    assert (a.purpose, a.order_id, a.topup_id, a.number, a.user_id) == (
        "order",
        order.id,
        None,
        order.number,
        order.user_id,
    )
    assert (a.amount_uzs, a.status, a.provider_ref) == (PRICE, "created", f"payme:{order.number}")
    b = await ensure_attempt(
        db_session, payable=await resolve(db_session, order.number, lock=True), provider="payme"
    )
    assert b.id == a.id
    other = await ensure_attempt(
        db_session, payable=await resolve(db_session, order.number, lock=True), provider="click"
    )
    assert other.id != a.id
    await db_session.commit()


async def test_ensure_attempt_refuses_a_paid_order(db_session: AsyncSession) -> None:
    order = await make_order(db_session, status="paid")
    with pytest.raises(AlreadyPaidError):
        await ensure_attempt(
            db_session, payable=await resolve(db_session, order.number, lock=True), provider="uzum"
        )
    await db_session.rollback()
    count = await db_session.scalar(select(func.count()).select_from(Payment))
    assert count == 0


async def test_ensure_attempt_needs_something_to_pay(db_session: AsyncSession) -> None:
    for account in ("K7M3Q9X2", "TZZZZZZZ"):
        with pytest.raises(ValueError, match="nothing to pay"):
            await ensure_attempt(
                db_session, payable=await resolve(db_session, account), provider="payme"
            )


async def test_settle_pays_the_order_and_notifies_once(db_session: AsyncSession) -> None:
    order, p = await _attempt(db_session)
    async with listen_orders() as listener:
        await mark_pending(db_session, payment=p)
        await settle(db_session, payment=p, event_id="payme:e1")
        assert await listener.drain() == []  # nothing before the commit
        await db_session.commit()
        assert await listener.drain() == [order.number]
        await settle(db_session, payment=p, event_id="payme:e1-replay")  # a retried callback
        await db_session.commit()
        assert await listener.drain() == [order.number]
    paid = await _order(db_session, order.id)
    assert (paid.status, paid.paid_with) == ("paid", "payme")
    assert paid.paid_at is not None
    assert (p.status, p.extra_metadata) == ("succeeded", {"settle_event_id": "payme:e1"})
    # A kassa-paid order books nothing on the buyer's balance.
    assert await user_balance(db_session, order.user_id) == Decimal(0)
    assert await db_session.scalar(select(func.count()).select_from(WalletTransaction)) == 0


async def test_a_second_settle_through_another_attempt_is_refused(
    db_session: AsyncSession,
) -> None:
    order, payme = await _attempt(db_session, provider="payme")
    order_id, number = order.id, order.number
    click = await ensure_attempt(
        db_session, payable=await resolve(db_session, order.number, lock=True), provider="click"
    )
    await mark_pending(db_session, payment=click)
    await db_session.commit()
    async with listen_orders() as listener:
        await settle(db_session, payment=payme, event_id="payme:e1")
        await db_session.commit()
        with pytest.raises(AlreadyPaidError):
            await settle(db_session, payment=click, event_id="click:e2")
        await db_session.rollback()
        assert await listener.drain() == [number]
    await db_session.refresh(click)
    assert click.status == "pending"
    assert (await _order(db_session, order_id)).paid_with == "payme"


async def test_settle_refuses_a_cancelled_order(db_session: AsyncSession) -> None:
    order, p = await _attempt(db_session)
    await mark_pending(db_session, payment=p)
    order.status = "cancelled"
    await db_session.commit()
    with pytest.raises(AlreadyPaidError):
        await settle(db_session, payment=p, event_id="e1")
    await db_session.rollback()
    await db_session.refresh(p)
    assert p.status == "pending"


async def test_a_late_settle_on_a_held_attempt_still_pays(db_session: AsyncSession) -> None:
    """A kassa held the attempt across ``expires_at`` (the expiry sweep leaves such an order):
    the money arrived, so the order is paid."""
    order, p = await _attempt(db_session)
    await mark_pending(db_session, payment=p)
    order.expires_at = clock.now() - timedelta(minutes=5)
    await db_session.commit()
    assert (await resolve(db_session, order.number)).reason == "expired"
    await settle(db_session, payment=p, event_id="late")
    await db_session.commit()
    assert (await _order(db_session, order.id)).status == "paid"


async def test_a_kassa_can_never_reverse_an_order(db_session: AsyncSession) -> None:
    order, p = await _attempt(db_session)
    order_id = order.id
    await settle(db_session, payment=p, event_id="e1")
    await db_session.commit()
    with pytest.raises(OrderReversalRefusedError) as caught:
        await reverse(db_session, payment=p, event_id="r1")
    assert isinstance(caught.value, ReversalRefusedError)
    await db_session.rollback()
    await db_session.refresh(p)
    assert p.status == "succeeded"
    assert (await _order(db_session, order_id)).status == "paid"


def test_reversal_refusals_share_one_base() -> None:
    assert issubclass(TopupSpentError, ReversalRefusedError)
    assert issubclass(OrderReversalRefusedError, ReversalRefusedError)
    assert ReversalRefusedError.type_uri == "https://csmarket.uz/errors/reversal-refused"
    assert TopupSpentError.type_uri == "https://csmarket.uz/errors/topup-spent"
    assert OrderReversalRefusedError.type_uri == "https://csmarket.uz/errors/order-reversal-refused"


async def test_cancel_pending_leaves_the_order_pending(db_session: AsyncSession) -> None:
    order, p = await _attempt(db_session)
    await mark_pending(db_session, payment=p)
    await cancel_pending(db_session, payment=p)
    await db_session.commit()
    assert p.status == "cancelled"
    assert (await _order(db_session, order.id)).status == "pending"


async def test_settle_and_a_kassa_create_on_one_order_do_not_deadlock(
    db_engine: AsyncEngine,
) -> None:
    """A create (order → attempt) racing a settle of that attempt: same lock order."""
    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    async with factory() as setup:
        order, p = await _attempt(setup)
    creator_has_order = asyncio.Event()

    async def _create() -> str:
        async with factory() as db:
            payable = await resolve(db, order.number, lock=True)
            creator_has_order.set()
            await asyncio.sleep(0.3)  # the settle now queues on the order row
            attempt = await ensure_attempt(db, payable=payable, provider="payme")
            await mark_pending(db, payment=attempt)
            await db.commit()
            return "created"

    async def _settle() -> str:
        await creator_has_order.wait()
        async with factory() as db:
            payment = await db.get(Payment, p.id)
            assert payment is not None
            await settle(db, payment=payment, event_id="e1")
            await db.commit()
            return "settled"

    outcomes = await asyncio.wait_for(asyncio.gather(_create(), _settle()), timeout=10)
    assert list(outcomes) == ["created", "settled"]
    async with factory() as check:
        settled = await check.get(Payment, p.id)
        assert settled is not None
        assert settled.status == "succeeded"
        assert (await _order(check, order.id)).status == "paid"
