"""The Payme 12-hour sweep (``payme.cancel_stale``) against a real Postgres.

No sleeping: ``create_time`` (Payme epoch ms) is set back past ``TIMEOUT`` directly.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from decimal import Decimal

import pytest
from csmarket.core import clock
from csmarket.modules.payme import service as payme_svc
from csmarket.modules.payme.api import TIMEOUT, cancel_stale
from csmarket.modules.payme.models import PaymeTransaction
from csmarket.modules.payments.models import Payment, WalletTopup
from csmarket.modules.payments.payable import resolve
from csmarket.modules.payments.topups import expire_stale
from csmarket.modules.wallet.api import user_balance
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from tests.integration.payments_factory import make_topup

TIYIN = 5_000_000
_HOUR_MS = 3_600_000
_TIMEOUT_MS = int(TIMEOUT.total_seconds() * 1000)


async def _create(db: AsyncSession, topup: WalletTopup, payme_id: str, *, age_ms: int) -> None:
    await payme_svc.create_transaction(
        db,
        payme_id=payme_id,
        time=payme_svc.now_ms() - age_ms,
        amount=TIYIN,
        account={"order": topup.number},
    )
    await db.commit()


async def _row(db: AsyncSession, payme_id: str) -> tuple[PaymeTransaction, Payment]:
    txn = (
        await db.execute(
            select(PaymeTransaction)
            .where(PaymeTransaction.payme_id == payme_id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    payment = (
        await db.execute(
            select(Payment)
            .where(Payment.id == txn.payment_id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    return txn, payment


async def test_a_stale_created_transaction_is_cancelled_with_reason_4(
    db_session: AsyncSession,
) -> None:
    topup = await make_topup(db_session)
    await _create(db_session, topup, "stale", age_ms=13 * _HOUR_MS)
    before = payme_svc.now_ms()
    assert await cancel_stale(db_session) == 1
    await db_session.commit()
    txn, payment = await _row(db_session, "stale")
    assert (txn.state, txn.reason, payment.status) == (-1, 4, "cancelled")
    assert txn.cancel_time >= before
    assert txn.perform_time == 0
    assert await cancel_stale(db_session) == 0


async def test_a_fresh_created_transaction_is_untouched(db_session: AsyncSession) -> None:
    topup = await make_topup(db_session)
    await _create(db_session, topup, "fresh", age_ms=_TIMEOUT_MS - _HOUR_MS)
    assert await cancel_stale(db_session) == 0
    txn, payment = await _row(db_session, "fresh")
    assert (txn.state, txn.reason, txn.cancel_time, payment.status) == (1, None, 0, "pending")


async def test_a_performed_transaction_is_never_touched(db_session: AsyncSession) -> None:
    topup = await make_topup(db_session)
    await _create(db_session, topup, "performed", age_ms=13 * _HOUR_MS)
    await payme_svc.perform_transaction(db_session, payme_id="performed")
    await db_session.commit()
    assert await cancel_stale(db_session) == 0
    txn, payment = await _row(db_session, "performed")
    assert (txn.state, payment.status) == (2, "succeeded")


async def test_an_empty_sweep_is_a_noop(db_session: AsyncSession) -> None:
    assert await cancel_stale(db_session) == 0


async def test_after_the_sweep_the_expired_topup_is_closed(db_session: AsyncSession) -> None:
    """The Payme sweep releases the attempt; the top-up expiry sweep then closes the top-up."""
    topup = await make_topup(db_session)
    await _create(db_session, topup, "close", age_ms=13 * _HOUR_MS)
    topup.expires_at = clock.now() - timedelta(minutes=1)
    await db_session.commit()
    assert await expire_stale(db_session) == 0  # Payme still holds it
    await db_session.commit()

    assert await cancel_stale(db_session) == 1
    await db_session.commit()
    assert await expire_stale(db_session) == 1
    await db_session.commit()
    await db_session.refresh(topup)
    assert topup.status == "expired"


async def test_a_new_payme_transaction_after_the_sweep_can_pay(db_session: AsyncSession) -> None:
    topup = await make_topup(db_session)
    await _create(db_session, topup, "swept", age_ms=13 * _HOUR_MS)
    assert await cancel_stale(db_session) == 1
    await db_session.commit()
    await _create(db_session, topup, "after", age_ms=0)
    await payme_svc.perform_transaction(db_session, payme_id="after")
    await db_session.commit()
    assert await user_balance(db_session, topup.user_id) == Decimal(50000)


async def test_a_failing_row_does_not_stop_the_sweep(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    first, second = await make_topup(db_session), await make_topup(db_session)
    await _create(db_session, first, "fail-first", age_ms=14 * _HOUR_MS)  # swept first
    await _create(db_session, second, "fail-second", age_ms=13 * _HOUR_MS)

    real = payme_svc._cancel_created
    calls = {"n": 0}

    async def first_row_fails(db: AsyncSession, txn: PaymeTransaction, *, reason: int) -> None:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("boom")
        await real(db, txn, reason=reason)

    monkeypatch.setattr(payme_svc, "_cancel_created", first_row_fails)
    assert await cancel_stale(db_session) == 1
    await db_session.commit()
    assert (await _row(db_session, "fail-first"))[0].state == 1
    assert (await _row(db_session, "fail-second"))[0].state == -1


async def test_a_row_performed_after_the_scan_is_left_alone(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The scan saw state 1; by the row lock it is 2 — the re-check skips it."""
    topup = await make_topup(db_session)
    await _create(db_session, topup, "raced", age_ms=13 * _HOUR_MS)
    real = payme_svc._lock_txn

    async def performed_meanwhile(db: AsyncSession, txn_id: str) -> PaymeTransaction:
        await db.execute(
            update(PaymeTransaction).where(PaymeTransaction.id == txn_id).values(state=2)
        )
        return await real(db, txn_id)

    monkeypatch.setattr(payme_svc, "_lock_txn", performed_meanwhile)
    assert await cancel_stale(db_session) == 0


async def test_the_scan_skips_a_topup_a_callback_holds(
    db_session: AsyncSession, db_engine: AsyncEngine
) -> None:
    """A top-up locked by an in-flight call is skipped, not waited for (SKIP LOCKED)."""
    topup = await make_topup(db_session)
    await _create(db_session, topup, "held", age_ms=13 * _HOUR_MS)

    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    async with factory() as holder, holder.begin():
        await resolve(holder, topup.number, lock=True)
        async with factory() as sweeper:
            count = await asyncio.wait_for(cancel_stale(sweeper), timeout=5)
            await sweeper.commit()
    assert count == 0
    assert (await _row(db_session, "held"))[0].state == 1
    assert await cancel_stale(db_session) == 1
