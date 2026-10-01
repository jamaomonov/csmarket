"""``uzum_transactions`` against a real Postgres: defaults, the unique ``trans_id`` that makes
every method replay-safe, the status check, and the attempt foreign key."""

from __future__ import annotations

import pytest
from csmarket.modules.payments.hooks import ensure_attempt
from csmarket.modules.payments.models import Payment
from csmarket.modules.payments.payable import resolve
from csmarket.modules.uzum.models import UzumTransaction
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.payments_factory import make_topup


async def _attempt(db: AsyncSession) -> tuple[str, Payment]:
    topup = await make_topup(db)
    payment = await ensure_attempt(
        db, payable=await resolve(db, topup.number, lock=True), provider="uzum"
    )
    await db.commit()
    return topup.number, payment


def _row(trans_id: str, payment: Payment, number: str, status: str = "CREATED") -> UzumTransaction:
    return UzumTransaction(
        trans_id=trans_id,
        payment_id=payment.id,
        account=number,
        amount_tiyin=5_000_000,
        status=status,
    )


async def test_uzum_transaction_round_trips_with_defaults(db_session: AsyncSession) -> None:
    number, payment = await _attempt(db_session)
    txn = _row("5c398d7e-76b6-11ee-96da-f3a095c6289d", payment, number)
    db_session.add(txn)
    await db_session.commit()
    fetched = (
        await db_session.execute(
            select(UzumTransaction)
            .where(UzumTransaction.id == txn.id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    assert len(fetched.id) == 36
    assert (fetched.account, fetched.amount_tiyin, fetched.status) == (number, 5_000_000, "CREATED")
    assert fetched.service_id is None
    assert (fetched.create_time, fetched.confirm_time, fetched.reverse_time) == (0, None, None)
    assert fetched.payment_source == {}
    assert fetched.created_at is not None
    assert fetched.updated_at is not None


async def test_a_duplicate_trans_id_is_rejected(db_session: AsyncSession) -> None:
    number, payment = await _attempt(db_session)
    db_session.add(_row("dup-trans-id", payment, number))
    await db_session.flush()
    db_session.add(_row("dup-trans-id", payment, number, status="FAILED"))
    with pytest.raises(IntegrityError, match="uq_uzum_transactions_trans_id"):
        async with db_session.begin_nested():
            await db_session.flush()


async def test_the_status_check_rejects_other_values(db_session: AsyncSession) -> None:
    number, payment = await _attempt(db_session)
    db_session.add(_row("bad-status", payment, number, status="BOGUS"))
    with pytest.raises(IntegrityError, match="ck_uzum_transactions_status"):
        async with db_session.begin_nested():
            await db_session.flush()


async def test_a_row_needs_a_real_attempt(db_session: AsyncSession) -> None:
    db_session.add(
        UzumTransaction(
            trans_id="orphan",
            payment_id="00000000-0000-0000-0000-000000000000",
            account="T0000000",
            amount_tiyin=1,
            status="CREATED",
        )
    )
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await db_session.flush()
