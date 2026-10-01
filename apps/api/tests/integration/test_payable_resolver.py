"""The payable resolver (ruling R5): account value → top-up, and whether it is payable."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from csmarket.core import clock
from csmarket.modules.payments.payable import resolve
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.payments_factory import make_topup


async def test_pending_topup_is_payable(db_session: AsyncSession) -> None:
    t = await make_topup(db_session, amount=Decimal(50000))
    p = await resolve(db_session, t.number)
    assert (p.kind, p.payable, p.reason, p.amount_uzs) == ("topup", True, "ok", Decimal(50000))
    assert (p.number, p.user_id, p.topup) == (t.number, t.user_id, t)


async def test_paid_expired_reversed_are_not_payable(db_session: AsyncSession) -> None:
    for status, reason in (("succeeded", "paid"), ("expired", "expired"), ("reversed", "reversed")):
        t = await make_topup(db_session, status=status)
        p = await resolve(db_session, t.number)
        assert (p.payable, p.reason) == (False, reason)


async def test_pending_past_expiry_is_not_payable(db_session: AsyncSession) -> None:
    t = await make_topup(db_session, expires_at=clock.now() - timedelta(seconds=1))
    assert (await resolve(db_session, t.number)).reason == "expired"


async def test_unknown_and_order_numbers_are_not_found(db_session: AsyncSession) -> None:
    for account in ("TZZZZZZZ", "7K3M9QX2", "", "drop table", "t1234567"):
        p = await resolve(db_session, account)
        assert (p.payable, p.reason, p.topup) == (False, "not_found", None)
    assert (await resolve(db_session, "TZZZZZZZ")).kind == "topup"
    assert (await resolve(db_session, "7K3M9QX2")).kind == "order"


async def test_lock_rereads_the_row(db_session: AsyncSession) -> None:
    t = await make_topup(db_session)
    # Another transaction changed the row behind the session's back.
    await db_session.execute(
        text("UPDATE wallet_topups SET status = 'succeeded' WHERE id = :id"), {"id": t.id}
    )
    assert (await resolve(db_session, t.number)).reason == "ok"  # the identity map's copy
    p = await resolve(db_session, t.number, lock=True)
    assert (p.reason, p.topup is t, t.status) == ("paid", True, "succeeded")
    await db_session.rollback()
