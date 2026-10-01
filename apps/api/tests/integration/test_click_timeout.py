"""The Click stale-prepare sweep (``click.cancel_stale``) against a real Postgres.

No sleeping: ``prepare_time`` is moved back past ``PREPARE_TIMEOUT`` directly.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest
from csmarket.core import clock
from csmarket.modules.click import service as click_svc
from csmarket.modules.click.api import PREPARE_TIMEOUT, cancel_stale
from csmarket.modules.click.models import ClickTransaction
from csmarket.modules.payments.models import Payment, WalletTopup
from csmarket.modules.payments.payable import resolve
from csmarket.modules.payments.topups import expire_stale
from csmarket.modules.wallet.api import user_balance
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from tests.integration.payments_factory import make_topup

SERVICE_ID = 108149
_STALE = PREPARE_TIMEOUT + timedelta(minutes=1)


async def _prepare(db: AsyncSession, topup: WalletTopup, trans_id: int) -> dict[str, Any]:
    result = await click_svc.prepare(
        db,
        click_trans_id=trans_id,
        service_id=SERVICE_ID,
        click_paydoc_id=trans_id,
        merchant_trans_id=topup.number,
        amount="50000",
    )
    await db.commit()
    return dict(result)


async def _age(db: AsyncSession, trans_id: int, by: timedelta) -> None:
    await db.execute(
        update(ClickTransaction)
        .where(ClickTransaction.click_trans_id == trans_id)
        .values(prepare_time=clock.now() - by)
    )
    await db.commit()


async def _row(db: AsyncSession, trans_id: int) -> tuple[ClickTransaction, Payment]:
    txn = (
        await db.execute(
            select(ClickTransaction)
            .where(ClickTransaction.click_trans_id == trans_id)
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


async def test_a_stale_prepared_transaction_is_cancelled(db_session: AsyncSession) -> None:
    topup = await make_topup(db_session)
    await _prepare(db_session, topup, 9001)
    await _age(db_session, 9001, _STALE)

    assert await cancel_stale(db_session) == 1
    await db_session.commit()
    txn, payment = await _row(db_session, 9001)
    assert (txn.status, payment.status) == ("CANCELLED", "cancelled")
    assert txn.cancel_time is not None
    assert txn.complete_time is None
    assert await cancel_stale(db_session) == 0


async def test_a_fresh_prepared_transaction_is_untouched(db_session: AsyncSession) -> None:
    topup = await make_topup(db_session)
    await _prepare(db_session, topup, 9002)
    await _age(db_session, 9002, timedelta(minutes=5))
    assert await cancel_stale(db_session) == 0
    txn, payment = await _row(db_session, 9002)
    assert (txn.status, payment.status) == ("PREPARED", "pending")


async def test_a_confirmed_transaction_is_never_touched(db_session: AsyncSession) -> None:
    topup = await make_topup(db_session)
    prepared = await _prepare(db_session, topup, 9003)
    await click_svc.complete(
        db_session,
        click_trans_id=9003,
        service_id=SERVICE_ID,
        merchant_trans_id=topup.number,
        merchant_prepare_id=prepared["merchant_prepare_id"],
        amount="50000",
    )
    await db_session.commit()
    await _age(db_session, 9003, _STALE)
    assert await cancel_stale(db_session) == 0
    txn, payment = await _row(db_session, 9003)
    assert (txn.status, payment.status) == ("CONFIRMED", "succeeded")


async def test_an_empty_sweep_is_a_noop(db_session: AsyncSession) -> None:
    assert await cancel_stale(db_session) == 0


async def test_a_stale_row_whose_sibling_settled_the_attempt_leaves_it(
    db_session: AsyncSession,
) -> None:
    topup = await make_topup(db_session)
    await _prepare(db_session, topup, 9004)
    b = await _prepare(db_session, topup, 9005)
    await click_svc.complete(
        db_session,
        click_trans_id=9005,
        service_id=SERVICE_ID,
        merchant_trans_id=topup.number,
        merchant_prepare_id=b["merchant_prepare_id"],
        amount="50000",
    )
    await db_session.commit()
    await _age(db_session, 9004, _STALE)

    assert await cancel_stale(db_session) == 1
    await db_session.commit()
    txn, payment = await _row(db_session, 9004)
    assert (txn.status, payment.status) == ("CANCELLED", "succeeded")
    await db_session.refresh(topup)
    assert topup.status == "succeeded"
    assert await user_balance(db_session, topup.user_id) == Decimal(50000)


async def test_after_the_sweep_the_expired_topup_is_closed(db_session: AsyncSession) -> None:
    """The Click sweep releases the attempt; the top-up expiry sweep then closes the top-up."""
    topup = await make_topup(db_session)
    await _prepare(db_session, topup, 9006)
    await _age(db_session, 9006, _STALE)
    topup.expires_at = clock.now() - timedelta(minutes=1)
    await db_session.commit()
    assert await expire_stale(db_session) == 0  # Click still holds it
    await db_session.commit()

    assert await cancel_stale(db_session) == 1
    await db_session.commit()
    assert await expire_stale(db_session) == 1
    await db_session.commit()
    await db_session.refresh(topup)
    assert topup.status == "expired"


async def test_a_failing_row_does_not_stop_the_sweep(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    first, second = await make_topup(db_session), await make_topup(db_session)
    await _prepare(db_session, first, 9007)
    await _prepare(db_session, second, 9008)
    await _age(db_session, 9007, _STALE + timedelta(minutes=1))  # swept first
    await _age(db_session, 9008, _STALE)

    real = click_svc._cancel_locked
    calls = {"n": 0}

    async def first_row_fails(db: AsyncSession, txn: ClickTransaction) -> None:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("boom")
        await real(db, txn)

    monkeypatch.setattr(click_svc, "_cancel_locked", first_row_fails)
    assert await cancel_stale(db_session) == 1
    await db_session.commit()
    assert (await _row(db_session, 9007))[0].status == "PREPARED"
    assert (await _row(db_session, 9008))[0].status == "CANCELLED"


async def test_the_scan_skips_a_topup_a_callback_holds(
    db_session: AsyncSession, db_engine: AsyncEngine
) -> None:
    """A top-up locked by an in-flight callback is skipped, not waited for (SKIP LOCKED);
    the row is still ``PREPARED`` for the next tick."""
    topup = await make_topup(db_session)
    await _prepare(db_session, topup, 9009)
    await _age(db_session, 9009, _STALE)

    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    async with factory() as holder, holder.begin():
        await resolve(holder, topup.number, lock=True)
        async with factory() as sweeper:
            count = await asyncio.wait_for(cancel_stale(sweeper), timeout=5)
            await sweeper.commit()
    assert count == 0
    assert (await _row(db_session, 9009))[0].status == "PREPARED"
    assert await cancel_stale(db_session) == 1
