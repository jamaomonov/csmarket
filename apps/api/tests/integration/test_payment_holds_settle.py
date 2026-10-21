"""settle holds money over a limit (spec 2026-10-21, «Hold»)."""

from __future__ import annotations

from decimal import Decimal

import pytest
from csmarket.modules.payments.api import (
    AlreadyPaidError,
    Payment,
    WalletTopup,
    credit_received_transfer,
    ensure_attempt,
    resolve,
    settle,
)
from csmarket.modules.risk.api import PaymentHold
from csmarket.modules.users.api import User
from csmarket.modules.wallet.api import user_balance
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.orders_factory import listen_orders, make_order
from tests.integration.payments_factory import make_topup, make_user
from tests.integration.risk_factory import set_kassa_limit

pytestmark = pytest.mark.asyncio


async def _topup_attempt(
    db: AsyncSession, amount: int, provider: str = "payme"
) -> tuple[User, WalletTopup, Payment]:
    user = await make_user(db)
    t = await make_topup(db, user=user, amount=Decimal(amount))
    p = await ensure_attempt(db, payable=await resolve(db, t.number, lock=True), provider=provider)
    await db.commit()
    return user, t, p


async def test_topup_over_limit_is_held_not_credited(db_session: AsyncSession) -> None:
    await set_kassa_limit(db_session, "payme", 1_000_000)
    user, t, p = await _topup_attempt(db_session, 1_500_000)
    await settle(db_session, payment=p, event_id="e1")
    await db_session.commit()
    await db_session.refresh(t)
    assert (t.status, p.status) == ("held", "succeeded")
    assert t.payment_id == p.id
    assert await user_balance(db_session, user.id) == Decimal(0)
    hold = await db_session.scalar(select(PaymentHold).where(PaymentHold.payment_id == p.id))
    assert hold is not None
    assert (hold.kind, hold.reason, hold.decision) == ("topup", "kassa_limit", None)
    assert hold.window_sum_uzs == Decimal(1_500_000)
    assert hold.limit_uzs == Decimal(1_000_000)
    assert (hold.provider, hold.amount_uzs, hold.user_id) == ("payme", Decimal(1_500_000), user.id)


async def test_topup_under_limit_credits_as_before(db_session: AsyncSession) -> None:
    await set_kassa_limit(db_session, "payme", 1_000_000)
    user, t, p = await _topup_attempt(db_session, 1_000_000)
    await settle(db_session, payment=p, event_id="e1")
    await db_session.commit()
    await db_session.refresh(t)
    assert t.status == "succeeded"
    assert await user_balance(db_session, user.id) == Decimal(1_000_000)
    n = await db_session.scalar(select(func.count()).select_from(PaymentHold))
    assert n == 0


async def test_order_over_limit_is_held_without_notify(db_session: AsyncSession) -> None:
    await set_kassa_limit(db_session, "payme", 1)
    order = await make_order(db_session)
    p = await ensure_attempt(
        db_session, payable=await resolve(db_session, order.number, lock=True), provider="payme"
    )
    await db_session.commit()
    async with listen_orders() as heard:
        await settle(db_session, payment=p, event_id="e1")
        await db_session.commit()
        assert await heard.drain() == []
    await db_session.refresh(order)
    assert (order.status, order.paid_with, order.paid_at) == ("held", "payme", None)
    assert p.status == "succeeded"
    hold = await db_session.scalar(select(PaymentHold).where(PaymentHold.payment_id == p.id))
    assert hold is not None
    assert hold.kind == "order"


async def test_retried_settle_of_held_payment_is_noop(db_session: AsyncSession) -> None:
    await set_kassa_limit(db_session, "payme", 1)
    _, t, p = await _topup_attempt(db_session, 50_000)
    await settle(db_session, payment=p, event_id="e1")
    await db_session.commit()
    await settle(db_session, payment=p, event_id="e1")
    await db_session.commit()
    n = await db_session.scalar(
        select(func.count()).select_from(PaymentHold).where(PaymentHold.payment_id == p.id)
    )
    assert n == 1


async def test_held_topup_is_not_payable_again(db_session: AsyncSession) -> None:
    await set_kassa_limit(db_session, "payme", 1)
    _, t, p = await _topup_attempt(db_session, 50_000)
    await settle(db_session, payment=p, event_id="e1")
    await db_session.commit()
    payable = await resolve(db_session, t.number)
    assert payable.reason == "paid"
    with pytest.raises(AlreadyPaidError):
        await ensure_attempt(db_session, payable=payable, provider="click")


async def test_second_attempt_on_held_topup_is_refused_at_settle(
    db_session: AsyncSession,
) -> None:
    await set_kassa_limit(db_session, "payme", 1)
    _, t, p = await _topup_attempt(db_session, 50_000)
    p2 = await ensure_attempt(
        db_session, payable=await resolve(db_session, t.number, lock=True), provider="click"
    )
    await db_session.commit()
    await settle(db_session, payment=p, event_id="e1")
    await db_session.commit()
    with pytest.raises(AlreadyPaidError):
        await settle(db_session, payment=p2, event_id="e2")


async def test_credit_received_transfer_is_never_held(db_session: AsyncSession) -> None:
    await set_kassa_limit(db_session, "p2p", 1)
    user = await make_user(db_session)
    topup = await credit_received_transfer(
        db_session,
        user_id=user.id,
        amount_uzs=Decimal(3_000_000),
        provider="p2p",
        event_id="hand-1",
    )
    await db_session.commit()
    assert topup.status == "succeeded"
    assert await user_balance(db_session, user.id) == Decimal(3_000_000)
