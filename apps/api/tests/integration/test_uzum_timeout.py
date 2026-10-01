"""The Uzum 30-minute sweep (``uzum.fail_stale``) against a real Postgres.

No sleeping: ``create_time`` (epoch ms) is set back past ``TIMEOUT`` directly.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from decimal import Decimal

import pytest
from csmarket.core import clock
from csmarket.modules.payments.models import Payment, WalletTopup
from csmarket.modules.payments.payable import resolve
from csmarket.modules.payments.topups import expire_stale
from csmarket.modules.uzum import service as uzum_svc
from csmarket.modules.uzum.api import TIMEOUT, fail_stale
from csmarket.modules.uzum.models import UzumTransaction
from csmarket.modules.wallet.api import user_balance
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from tests.integration.payments_factory import make_topup

TIYIN = 5_000_000
_MINUTE_MS = 60_000
_TIMEOUT_MS = int(TIMEOUT.total_seconds() * 1000)


async def _create(db: AsyncSession, topup: WalletTopup, trans_id: str, *, age_ms: int) -> None:
    await uzum_svc.create(
        db, service_id=101202, trans_id=trans_id, account=topup.number, amount=TIYIN
    )
    await db.execute(
        update(UzumTransaction)
        .where(UzumTransaction.trans_id == trans_id)
        .values(create_time=uzum_svc.now_ms() - age_ms)
    )
    await db.commit()


async def _row(db: AsyncSession, trans_id: str) -> tuple[UzumTransaction, Payment]:
    txn = (
        await db.execute(
            select(UzumTransaction)
            .where(UzumTransaction.trans_id == trans_id)
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


async def test_a_stale_created_transaction_fails_and_releases_the_attempt(
    db_session: AsyncSession,
) -> None:
    topup = await make_topup(db_session)
    await _create(db_session, topup, "stale", age_ms=31 * _MINUTE_MS)
    assert await fail_stale(db_session) == 1
    await db_session.commit()
    txn, payment = await _row(db_session, "stale")
    assert (txn.status, txn.confirm_time, txn.reverse_time) == ("FAILED", None, None)
    assert payment.status == "cancelled"
    assert await fail_stale(db_session) == 0


async def test_a_fresh_created_transaction_is_untouched(db_session: AsyncSession) -> None:
    topup = await make_topup(db_session)
    await _create(db_session, topup, "fresh", age_ms=_TIMEOUT_MS - _MINUTE_MS)
    assert await fail_stale(db_session) == 0
    txn, payment = await _row(db_session, "fresh")
    assert (txn.status, payment.status) == ("CREATED", "pending")


async def test_a_confirmed_transaction_is_never_touched(db_session: AsyncSession) -> None:
    topup = await make_topup(db_session)
    await _create(db_session, topup, "confirmed", age_ms=31 * _MINUTE_MS)
    await uzum_svc.confirm(db_session, trans_id="confirmed", payment_source={})
    await db_session.commit()
    assert await fail_stale(db_session) == 0
    txn, payment = await _row(db_session, "confirmed")
    assert (txn.status, payment.status) == ("CONFIRMED", "succeeded")


async def test_an_empty_sweep_is_a_noop(db_session: AsyncSession) -> None:
    assert await fail_stale(db_session) == 0


async def test_a_stale_row_whose_sibling_settled_the_attempt_leaves_it_alone(
    db_session: AsyncSession,
) -> None:
    """Two rows share one attempt; the sibling confirmed it. Failing the stale one must not
    touch the settled attempt or the credited top-up."""
    topup = await make_topup(db_session)
    await _create(db_session, topup, "sib-stale", age_ms=31 * _MINUTE_MS)
    await _create(db_session, topup, "sib-paid", age_ms=0)
    await uzum_svc.confirm(db_session, trans_id="sib-paid", payment_source={})
    await db_session.commit()
    assert await fail_stale(db_session) == 1
    await db_session.commit()
    txn, payment = await _row(db_session, "sib-stale")
    assert (txn.status, payment.status) == ("FAILED", "succeeded")
    assert await user_balance(db_session, topup.user_id) == Decimal(50000)


async def test_a_stale_row_with_a_live_sibling_keeps_the_attempt(db_session: AsyncSession) -> None:
    topup = await make_topup(db_session)
    await _create(db_session, topup, "keep-stale", age_ms=31 * _MINUTE_MS)
    await _create(db_session, topup, "keep-live", age_ms=0)
    assert await fail_stale(db_session) == 1
    await db_session.commit()
    _, payment = await _row(db_session, "keep-stale")
    assert payment.status == "pending"
    await uzum_svc.confirm(db_session, trans_id="keep-live", payment_source={})
    await db_session.commit()
    assert await user_balance(db_session, topup.user_id) == Decimal(50000)


async def test_after_the_sweep_the_expired_topup_is_closed(db_session: AsyncSession) -> None:
    """The Uzum sweep releases the attempt; the top-up expiry sweep then closes the top-up."""
    topup = await make_topup(db_session)
    await _create(db_session, topup, "close", age_ms=31 * _MINUTE_MS)
    topup.expires_at = clock.now() - timedelta(minutes=1)
    await db_session.commit()
    assert await expire_stale(db_session) == 0  # Uzum still holds it
    await db_session.commit()

    assert await fail_stale(db_session) == 1
    await db_session.commit()
    assert await expire_stale(db_session) == 1
    await db_session.commit()
    await db_session.refresh(topup)
    assert topup.status == "expired"


async def test_a_new_uzum_transaction_after_the_sweep_can_pay(db_session: AsyncSession) -> None:
    topup = await make_topup(db_session)
    await _create(db_session, topup, "swept", age_ms=31 * _MINUTE_MS)
    assert await fail_stale(db_session) == 1
    await db_session.commit()
    await _create(db_session, topup, "after", age_ms=0)
    await uzum_svc.confirm(db_session, trans_id="after", payment_source={})
    await db_session.commit()
    assert await user_balance(db_session, topup.user_id) == Decimal(50000)


async def test_a_failing_row_does_not_stop_the_sweep(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    first, second = await make_topup(db_session), await make_topup(db_session)
    await _create(db_session, first, "fail-first", age_ms=40 * _MINUTE_MS)  # swept first
    await _create(db_session, second, "fail-second", age_ms=35 * _MINUTE_MS)

    real = uzum_svc._fail_created
    calls = {"n": 0}

    async def first_row_fails(db: AsyncSession, txn: UzumTransaction) -> None:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("boom")
        await real(db, txn)

    monkeypatch.setattr(uzum_svc, "_fail_created", first_row_fails)
    assert await fail_stale(db_session) == 1
    await db_session.commit()
    assert (await _row(db_session, "fail-first"))[0].status == "CREATED"
    assert (await _row(db_session, "fail-second"))[0].status == "FAILED"


async def test_a_row_confirmed_after_the_scan_is_left_alone(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The scan saw CREATED; by the row lock it is CONFIRMED — the re-check skips it."""
    topup = await make_topup(db_session)
    await _create(db_session, topup, "raced", age_ms=31 * _MINUTE_MS)
    real = uzum_svc._lock_txn

    async def confirmed_meanwhile(db: AsyncSession, txn_id: str) -> UzumTransaction:
        await db.execute(
            update(UzumTransaction).where(UzumTransaction.id == txn_id).values(status="CONFIRMED")
        )
        return await real(db, txn_id)

    monkeypatch.setattr(uzum_svc, "_lock_txn", confirmed_meanwhile)
    assert await fail_stale(db_session) == 0


async def test_the_scan_skips_a_topup_a_callback_holds(
    db_session: AsyncSession, db_engine: AsyncEngine
) -> None:
    """A top-up locked by an in-flight call is skipped, not waited for (SKIP LOCKED)."""
    topup = await make_topup(db_session)
    await _create(db_session, topup, "held", age_ms=31 * _MINUTE_MS)

    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    async with factory() as holder, holder.begin():
        await resolve(holder, topup.number, lock=True)
        async with factory() as sweeper:
            count = await asyncio.wait_for(fail_stale(sweeper), timeout=5)
            await sweeper.commit()
    assert count == 0
    assert (await _row(db_session, "held"))[0].status == "CREATED"
    assert await fail_stale(db_session) == 1
