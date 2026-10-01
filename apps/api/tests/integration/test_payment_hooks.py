"""Provider hooks (ruling R6): one credit per top-up, no overdraft, a strict FSM."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from decimal import Decimal

import pytest
from csmarket.core import clock
from csmarket.modules.payments.fsm import InvalidTransitionError
from csmarket.modules.payments.hooks import (
    AlreadyPaidError,
    TopupSpentError,
    cancel_pending,
    ensure_attempt,
    mark_pending,
    reverse,
    settle,
)
from csmarket.modules.payments.models import Payment, WalletTopup
from csmarket.modules.payments.payable import resolve
from csmarket.modules.wallet.api import (
    Leg,
    balance,
    credit_topup,
    ensure_account,
    post,
    reverse_topup,
    user_account,
    user_balance,
)
from csmarket.modules.wallet.models import WalletTransaction
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from tests.integration.orders_factory import make_order
from tests.integration.payments_factory import make_topup


async def _attempt(
    db: AsyncSession, provider: str = "payme", amount: Decimal = Decimal(50000)
) -> tuple[WalletTopup, Payment]:
    t = await make_topup(db, amount=amount)
    p = await ensure_attempt(db, payable=await resolve(db, t.number, lock=True), provider=provider)
    await db.commit()
    return t, p


async def _sibling(db: AsyncSession, t: WalletTopup, provider: str = "click") -> Payment:
    """Another kassa's attempt opened on ``t`` before the first one landed (a second tab)."""
    p = Payment(
        number=t.number,
        purpose="topup",
        topup_id=t.id,
        user_id=t.user_id,
        provider=provider,
        provider_ref=f"{provider}:{t.number}",
        amount_uzs=t.amount_uzs,
        status="pending",
    )
    db.add(p)
    await db.commit()
    return p


async def _tx_count(db: AsyncSession) -> int:
    return int(await db.scalar(select(func.count()).select_from(WalletTransaction)) or 0)


async def _clearing(db: AsyncSession, provider: str) -> Decimal:
    account = await ensure_account(
        db, owner_type="provider", owner_id=provider, kind="provider_clearing"
    )
    return await balance(db, account.id)


async def test_settle_credits_and_marks_topup(db_session: AsyncSession) -> None:
    t, p = await _attempt(db_session)
    await mark_pending(db_session, payment=p)
    await settle(db_session, payment=p, event_id="e1")
    await db_session.commit()
    await db_session.refresh(t)
    assert (p.status, t.status, t.payment_id) == ("succeeded", "succeeded", p.id)
    assert p.succeeded_at is not None
    assert t.succeeded_at == p.succeeded_at
    assert p.extra_metadata == {"settle_event_id": "e1"}
    assert await user_balance(db_session, t.user_id) == Decimal(50000)
    assert await _clearing(db_session, "payme") == Decimal(50000)
    txn = await db_session.scalar(select(WalletTransaction))
    assert txn is not None
    assert (txn.kind, txn.idempotency_key, txn.reference_type, txn.reference_id) == (
        "topup",
        f"topup:{t.id}",
        "topup",
        t.id,
    )


async def test_settle_twice_credits_once(db_session: AsyncSession) -> None:
    t, p = await _attempt(db_session)
    await settle(db_session, payment=p, event_id="e1")
    await settle(db_session, payment=p, event_id="e1-replay")
    await db_session.commit()
    assert await user_balance(db_session, t.user_id) == Decimal(50000)
    assert await _tx_count(db_session) == 1
    assert p.extra_metadata == {"settle_event_id": "e1"}


async def test_a_second_attempt_on_a_paid_topup_is_refused(db_session: AsyncSession) -> None:
    t, p1 = await _attempt(db_session, provider="payme")
    await settle(db_session, payment=p1, event_id="e1")
    await db_session.commit()
    p2 = await _sibling(db_session, t)
    uid = t.user_id
    with pytest.raises(AlreadyPaidError):
        await settle(db_session, payment=p2, event_id="e2")
    await db_session.rollback()
    await db_session.refresh(p2)
    assert p2.status == "pending"
    assert await user_balance(db_session, uid) == Decimal(50000)
    assert await _tx_count(db_session) == 1


async def test_a_second_attempt_on_a_reversed_topup_is_refused(db_session: AsyncSession) -> None:
    t, p1 = await _attempt(db_session)
    await settle(db_session, payment=p1, event_id="e1")
    await reverse(db_session, payment=p1, event_id="r1")
    await db_session.commit()
    p2 = await _sibling(db_session, t)
    uid = t.user_id
    with pytest.raises(AlreadyPaidError):
        await settle(db_session, payment=p2, event_id="e2")
    await db_session.rollback()
    assert await user_balance(db_session, uid) == Decimal(0)


async def test_a_late_settle_on_a_held_attempt_still_credits(db_session: AsyncSession) -> None:
    t, p = await _attempt(db_session)
    await mark_pending(db_session, payment=p)
    t.expires_at = clock.now() - timedelta(minutes=5)
    await db_session.commit()
    assert (await resolve(db_session, t.number)).reason == "expired"
    await settle(db_session, payment=p, event_id="late")
    await db_session.commit()
    assert (p.status, t.status) == ("succeeded", "succeeded")
    assert await user_balance(db_session, t.user_id) == Decimal(50000)


async def test_settle_refuses_a_cancelled_attempt(db_session: AsyncSession) -> None:
    t, p = await _attempt(db_session)
    await cancel_pending(db_session, payment=p)
    await db_session.commit()
    uid = t.user_id
    with pytest.raises(InvalidTransitionError):
        await settle(db_session, payment=p, event_id="e1")
    await db_session.rollback()
    assert await user_balance(db_session, uid) == Decimal(0)


async def test_reverse_unspent_claws_back(db_session: AsyncSession) -> None:
    t, p = await _attempt(db_session)
    await settle(db_session, payment=p, event_id="e1")
    await reverse(db_session, payment=p, event_id="r1")
    await db_session.commit()
    await db_session.refresh(t)
    assert (p.status, t.status) == ("refunded", "reversed")
    assert p.extra_metadata == {"settle_event_id": "e1", "reverse_event_id": "r1"}
    assert await user_balance(db_session, t.user_id) == Decimal(0)
    assert await _clearing(db_session, "payme") == Decimal(0)


async def test_reverse_twice_reverses_once(db_session: AsyncSession) -> None:
    t, p = await _attempt(db_session)
    await settle(db_session, payment=p, event_id="e1")
    await reverse(db_session, payment=p, event_id="r1")
    await db_session.commit()
    await reverse(db_session, payment=p, event_id="r1-replay")
    await db_session.commit()
    assert p.status == "refunded"
    assert await user_balance(db_session, t.user_id) == Decimal(0)
    assert await _tx_count(db_session) == 2


async def test_reverse_refused_when_spent(db_session: AsyncSession) -> None:
    t, p = await _attempt(db_session)
    await settle(db_session, payment=p, event_id="e1")
    await db_session.commit()
    # Spend 10 000 (stand-in for an M4 purchase).
    w = await user_account(db_session, t.user_id)
    house = await ensure_account(
        db_session, owner_type="house", owner_id="house", kind="house_payments_received"
    )
    await post(
        db_session,
        kind="admin_adjust",
        legs=[Leg(w.id, "C", Decimal(10000)), Leg(house.id, "D", Decimal(10000))],
        idempotency_key="spend",
    )
    await db_session.commit()
    with pytest.raises(TopupSpentError):
        await reverse(db_session, payment=p, event_id="r1")
    await db_session.rollback()
    await db_session.refresh(p)
    await db_session.refresh(t)
    assert (p.status, t.status) == ("succeeded", "succeeded")
    assert await user_balance(db_session, t.user_id) == Decimal(40000)


async def test_reverse_needs_a_succeeded_attempt(db_session: AsyncSession) -> None:
    _, p = await _attempt(db_session)
    with pytest.raises(InvalidTransitionError):
        await reverse(db_session, payment=p, event_id="r1")
    await db_session.rollback()


async def test_cancel_pending_only_touches_pending(db_session: AsyncSession) -> None:
    t, p = await _attempt(db_session)
    await settle(db_session, payment=p, event_id="e1")
    await cancel_pending(db_session, payment=p)
    await db_session.commit()
    assert p.status == "succeeded"
    t2, p2 = await _attempt(db_session)
    await mark_pending(db_session, payment=p2)
    await cancel_pending(db_session, payment=p2)
    await db_session.commit()
    assert p2.status == "cancelled"
    _, p3 = await _attempt(db_session)
    await cancel_pending(db_session, payment=p3)  # created → cancelled
    await cancel_pending(db_session, payment=p3)  # already cancelled: no-op
    await db_session.commit()
    assert p3.status == "cancelled"


async def test_mark_pending_is_idempotent_and_refuses_a_settled_attempt(
    db_session: AsyncSession,
) -> None:
    _, p = await _attempt(db_session)
    await mark_pending(db_session, payment=p)
    stamp = p.updated_at
    await mark_pending(db_session, payment=p)
    assert (p.status, p.updated_at) == ("pending", stamp)
    await settle(db_session, payment=p, event_id="e1")
    await db_session.commit()
    with pytest.raises(InvalidTransitionError):
        await mark_pending(db_session, payment=p)
    await db_session.rollback()


async def test_ensure_attempt_reuses_a_live_attempt_of_the_same_provider(
    db_session: AsyncSession,
) -> None:
    t = await make_topup(db_session)
    a = await ensure_attempt(
        db_session, payable=await resolve(db_session, t.number, lock=True), provider="payme"
    )
    b = await ensure_attempt(
        db_session, payable=await resolve(db_session, t.number, lock=True), provider="payme"
    )
    assert a.id == b.id
    assert (a.status, a.provider_ref, a.amount_uzs, a.user_id) == (
        "created",
        f"payme:{t.number}",
        t.amount_uzs,
        t.user_id,
    )
    await mark_pending(db_session, payment=a)
    await cancel_pending(db_session, payment=a)
    c = await ensure_attempt(
        db_session, payable=await resolve(db_session, t.number, lock=True), provider="payme"
    )
    assert c.id != a.id
    assert c.provider_ref == f"payme:{t.number}:{c.id}"  # unclaimed_external_id suffix
    other = await ensure_attempt(
        db_session, payable=await resolve(db_session, t.number, lock=True), provider="click"
    )
    assert other.id not in (a.id, c.id)
    assert other.provider_ref == f"click:{t.number}"
    await db_session.commit()


async def test_order_payables_are_not_implemented(db_session: AsyncSession) -> None:
    with pytest.raises(NotImplementedError):
        await ensure_attempt(
            db_session, payable=await resolve(db_session, "7K3M9QX2"), provider="payme"
        )
    order_row = await make_order(db_session)
    order = Payment(
        number=order_row.number,
        purpose="order",
        order_id=order_row.id,
        user_id=order_row.user_id,
        provider="payme",
        amount_uzs=Decimal(1000),
        status="pending",
    )
    db_session.add(order)
    await db_session.commit()
    with pytest.raises(NotImplementedError):
        await settle(db_session, payment=order, event_id="e1")
    with pytest.raises(NotImplementedError):
        await reverse(db_session, payment=order, event_id="r1")
    await db_session.rollback()


async def test_wallet_topup_postings_replay_by_key(db_session: AsyncSession) -> None:
    t = await make_topup(db_session)
    kw = {"user_id": t.user_id, "topup_id": t.id, "amount": Decimal(50000), "provider": "uzum"}
    first = await credit_topup(db_session, **kw)  # type: ignore[arg-type]
    assert (await credit_topup(db_session, **kw)).id == first.id  # type: ignore[arg-type]
    back = await reverse_topup(db_session, **kw)  # type: ignore[arg-type]
    # The replay is answered from the key, before the (now empty) balance is checked.
    assert (await reverse_topup(db_session, **kw)).id == back.id  # type: ignore[arg-type]
    assert back.idempotency_key == f"topup_reversal:{t.id}"
    assert await user_balance(db_session, t.user_id) == Decimal(0)
    await db_session.commit()


async def test_two_kassas_settling_one_topup_at_once_credit_once(db_engine: AsyncEngine) -> None:
    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    async with factory() as setup:
        t, payme = await _attempt(setup, provider="payme")
        click = await _sibling(setup, t)

    async def _settle(payment_id: str, event: str) -> str:
        async with factory() as db:
            payment = await db.get(Payment, payment_id)
            assert payment is not None
            try:
                await settle(db, payment=payment, event_id=event)
            except AlreadyPaidError:
                await db.rollback()
                return "refused"
            await db.commit()
            return "settled"

    outcomes = await asyncio.gather(_settle(payme.id, "e1"), _settle(click.id, "e2"))
    assert sorted(outcomes) == ["refused", "settled"]
    async with factory() as check:
        assert await user_balance(check, t.user_id) == Decimal(50000)
        assert await _tx_count(check) == 1


async def test_settle_and_a_kassa_create_on_one_topup_do_not_deadlock(
    db_engine: AsyncEngine,
) -> None:
    """A create (top-up → attempt) racing a settle of that attempt: same lock order."""
    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    async with factory() as setup:
        t, p = await _attempt(setup)
    creator_has_topup = asyncio.Event()

    async def _create() -> None:
        async with factory() as db:
            payable = await resolve(db, t.number, lock=True)
            creator_has_topup.set()
            await asyncio.sleep(0.3)  # the settle now queues on the top-up row
            attempt = await ensure_attempt(db, payable=payable, provider="payme")
            await mark_pending(db, payment=attempt)
            await db.commit()

    async def _settle() -> None:
        await creator_has_topup.wait()
        async with factory() as db:
            payment = await db.get(Payment, p.id)
            assert payment is not None
            await settle(db, payment=payment, event_id="e1")
            await db.commit()

    await asyncio.wait_for(asyncio.gather(_create(), _settle()), timeout=10)
    async with factory() as check:
        settled = await check.get(Payment, p.id)
        assert settled is not None
        assert settled.status == "succeeded"
        assert await user_balance(check, t.user_id) == Decimal(50000)


async def test_ensure_attempt_refuses_a_paid_or_reversed_topup(db_session: AsyncSession) -> None:
    t, p = await _attempt(db_session)
    number, topup_id = t.number, t.id
    await settle(db_session, payment=p, event_id="e1")
    await db_session.commit()
    with pytest.raises(AlreadyPaidError):
        await ensure_attempt(
            db_session, payable=await resolve(db_session, number, lock=True), provider="click"
        )
    await db_session.rollback()
    await reverse(db_session, payment=p, event_id="r1")
    await db_session.commit()
    with pytest.raises(AlreadyPaidError):
        await ensure_attempt(
            db_session, payable=await resolve(db_session, number, lock=True), provider="click"
        )
    await db_session.rollback()
    count = await db_session.scalar(
        select(func.count()).select_from(Payment).where(Payment.topup_id == topup_id)
    )
    assert count == 1


async def test_ensure_attempt_still_opens_on_an_expired_topup(db_session: AsyncSession) -> None:
    t = await make_topup(db_session, expires_at=clock.now() - timedelta(minutes=1))
    payable = await resolve(db_session, t.number, lock=True)
    assert payable.reason == "expired"
    p = await ensure_attempt(db_session, payable=payable, provider="mock")
    await db_session.commit()
    assert p.status == "created"


async def test_mark_pending_then_settle_racing_a_kassa_create_do_not_deadlock(
    db_engine: AsyncEngine,
) -> None:
    """``mark_pending`` locks the top-up first too, so a later ``settle`` in the same
    transaction never waits on a top-up a concurrent create holds while it waits on us."""
    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    async with factory() as setup:
        t, p = await _attempt(setup)
    marked = asyncio.Event()

    async def _mark_then_settle() -> str:
        async with factory() as db:
            payment = await db.get(Payment, p.id)
            assert payment is not None
            await mark_pending(db, payment=payment)
            marked.set()
            await asyncio.sleep(0.3)  # the create now queues (or would grab the top-up)
            await settle(db, payment=payment, event_id="e1")
            await db.commit()
            return "settled"

    async def _create() -> str:
        await marked.wait()
        async with factory() as db:
            payable = await resolve(db, t.number, lock=True)
            try:
                attempt = await ensure_attempt(db, payable=payable, provider="payme")
            except AlreadyPaidError:
                await db.rollback()
                return "refused"
            await mark_pending(db, payment=attempt)
            await db.commit()
            return "created"

    outcomes = await asyncio.wait_for(asyncio.gather(_mark_then_settle(), _create()), timeout=10)
    assert list(outcomes) == ["settled", "refused"]
    async with factory() as check:
        assert await user_balance(check, t.user_id) == Decimal(50000)
