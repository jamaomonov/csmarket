"""``payme_transactions`` against a real Postgres: defaults, the unique Payme id that makes
every method replay-safe, the state check, and the attempt foreign key."""

from __future__ import annotations

import pytest
from csmarket.modules.payme.models import PaymeTransaction
from csmarket.modules.payments.hooks import ensure_attempt
from csmarket.modules.payments.models import Payment
from csmarket.modules.payments.payable import resolve
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.payments_factory import make_topup


async def _attempt(db: AsyncSession) -> tuple[str, Payment]:
    topup = await make_topup(db)
    payment = await ensure_attempt(
        db, payable=await resolve(db, topup.number, lock=True), provider="payme"
    )
    await db.commit()
    return topup.number, payment


def _row(payme_id: str, payment: Payment, number: str, state: int = 1) -> PaymeTransaction:
    return PaymeTransaction(
        payme_id=payme_id,
        payment_id=payment.id,
        account=number,
        amount_tiyin=5_000_000,
        state=state,
    )


async def test_payme_transaction_round_trips_with_defaults(db_session: AsyncSession) -> None:
    number, payment = await _attempt(db_session)
    txn = _row("686cbf0f0a6e2d3d5c0e1234", payment, number)
    db_session.add(txn)
    await db_session.commit()
    fetched = (
        await db_session.execute(
            select(PaymeTransaction)
            .where(PaymeTransaction.id == txn.id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    assert len(fetched.id) == 36
    assert (fetched.account, fetched.amount_tiyin, fetched.state) == (number, 5_000_000, 1)
    assert fetched.reason is None
    assert (fetched.create_time, fetched.perform_time, fetched.cancel_time) == (0, 0, 0)
    assert fetched.fiscal_data == {}
    assert fetched.created_at is not None
    assert fetched.updated_at is not None


async def test_a_duplicate_payme_id_is_rejected(db_session: AsyncSession) -> None:
    number, payment = await _attempt(db_session)
    db_session.add(_row("dup-payme-id", payment, number))
    await db_session.flush()
    db_session.add(_row("dup-payme-id", payment, number, state=-1))
    with pytest.raises(IntegrityError, match="uq_payme_transactions_payme_id"):
        async with db_session.begin_nested():
            await db_session.flush()


async def test_the_state_check_rejects_other_values(db_session: AsyncSession) -> None:
    number, payment = await _attempt(db_session)
    db_session.add(_row("bad-state", payment, number, state=3))
    with pytest.raises(IntegrityError, match="ck_payme_transactions_state"):
        async with db_session.begin_nested():
            await db_session.flush()


async def test_a_row_needs_a_real_attempt(db_session: AsyncSession) -> None:
    db_session.add(
        PaymeTransaction(
            payme_id="orphan",
            payment_id="00000000-0000-0000-0000-000000000000",
            account="T0000000",
            amount_tiyin=1,
            state=1,
        )
    )
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await db_session.flush()
