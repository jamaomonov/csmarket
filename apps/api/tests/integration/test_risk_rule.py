"""The risk verdict (spec 2026-10-21-payment-risk-limits, «The rule»)."""

from __future__ import annotations

import asyncio
from decimal import Decimal
from unittest.mock import patch

import pytest
from csmarket.core.clock import now
from csmarket.modules.payments.api import Payment
from csmarket.modules.risk.api import verdict
from csmarket.modules.users.api import User
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from tests.integration.payments_factory import make_user
from tests.integration.risk_factory import (
    clear_kassa_limits,
    set_kassa_limit,
    set_policy,
    succeeded_payment,
)

pytestmark = pytest.mark.asyncio


async def _new(db: AsyncSession, user_id: str, amount: int, provider: str = "payme") -> Payment:
    """An unsettled attempt (the one being checked)."""
    user = await db.get_one(User, user_id)
    return await succeeded_payment(db, user, provider=provider, amount=amount, status="pending")


async def test_under_and_equal_pass(db_session: AsyncSession) -> None:
    await set_kassa_limit(db_session, "payme", 1_000_000)
    user = await make_user(db_session)
    await succeeded_payment(db_session, user, amount=600_000)
    current = await _new(db_session, user.id, 400_000)
    v = await verdict(db_session, current)
    assert v.hold is False


async def test_split_payments_over_the_window_are_held(db_session: AsyncSession) -> None:
    await set_kassa_limit(db_session, "payme", 1_000_000)
    user = await make_user(db_session)
    for _ in range(3):
        await succeeded_payment(db_session, user, amount=300_000, hours_ago=2)
    current = await _new(db_session, user.id, 200_000)
    v = await verdict(db_session, current)
    assert (v.hold, v.reason) == (True, "kassa_limit")
    assert v.window_sum_uzs == Decimal(1_100_000)
    assert v.limit_uzs == Decimal(1_000_000)


async def test_outside_window_and_other_kassa_do_not_count(db_session: AsyncSession) -> None:
    await set_kassa_limit(db_session, "payme", 1_000_000)
    user = await make_user(db_session)
    await succeeded_payment(db_session, user, amount=900_000, hours_ago=25)
    await succeeded_payment(db_session, user, provider="click", amount=900_000)
    current = await _new(db_session, user.id, 900_000)
    assert (await verdict(db_session, current)).hold is False


async def test_refunded_does_not_count(db_session: AsyncSession) -> None:
    await set_kassa_limit(db_session, "payme", 1_000_000)
    user = await make_user(db_session)
    await succeeded_payment(db_session, user, amount=900_000, status="refunded")
    current = await _new(db_session, user.id, 900_000)
    assert (await verdict(db_session, current)).hold is False


async def test_disabled_or_missing_limit_passes(db_session: AsyncSession) -> None:
    await clear_kassa_limits(db_session)
    await set_kassa_limit(db_session, "click", 1, enabled=False)
    user = await make_user(db_session)
    assert (await verdict(db_session, await _new(db_session, user.id, 5_000_000))).hold is False
    click = await _new(db_session, user.id, 5_000_000, "click")
    assert (await verdict(db_session, click)).hold is False


async def test_user_limit_spans_kassas(db_session: AsyncSession) -> None:
    await clear_kassa_limits(db_session)
    user = await make_user(db_session)
    await set_policy(db_session, user.id, max_amount_uzs=Decimal(1_000_000), window_hours=48)
    await succeeded_payment(db_session, user, provider="click", amount=700_000, hours_ago=30)
    v = await verdict(db_session, await _new(db_session, user.id, 400_000, "payme"))
    assert (v.hold, v.reason, v.limit_uzs) == (True, "user_limit", Decimal(1_000_000))


async def test_trusted_bypasses_both(db_session: AsyncSession) -> None:
    await set_kassa_limit(db_session, "payme", 1)
    user = await make_user(db_session)
    await set_policy(db_session, user.id, trusted=True, max_amount_uzs=Decimal(1))
    assert (await verdict(db_session, await _new(db_session, user.id, 5_000_000))).hold is False


async def test_an_error_holds_and_leaves_the_transaction_usable(db_session: AsyncSession) -> None:
    await set_kassa_limit(db_session, "payme", 1_000_000)
    user = await make_user(db_session)
    current = await _new(db_session, user.id, 1)
    with patch("csmarket.modules.risk.rule._kassa_limit", side_effect=RuntimeError("boom")):
        v = await verdict(db_session, current)
    assert (v.hold, v.reason, v.window_sum_uzs) == (True, "check_failed", None)
    await db_session.refresh(current)  # the session still works


async def test_a_lock_failure_raises_rather_than_holds(db_session: AsyncSession) -> None:
    # Fail-closed covers the checks; a failed lock aborts the caller's transaction, where
    # no hold could be written anyway, so the real error surfaces.
    user = await make_user(db_session)
    current = await _new(db_session, user.id, 1)
    with (
        patch("csmarket.modules.risk.rule.lock_user", side_effect=RuntimeError("lock")),
        pytest.raises(RuntimeError, match="lock"),
    ):
        await verdict(db_session, current)


async def test_two_settles_at_once_are_serialised(db_engine: AsyncEngine) -> None:
    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    async with factory() as db:
        await set_kassa_limit(db, "payme", 1_000_000)
        user = await make_user(db)
        a = await _new(db, user.id, 600_000)
        b = await _new(db, user.id, 600_000)

    async def _check(pid: str) -> bool:
        async with factory() as db:
            p = await db.get_one(Payment, pid)
            v = await verdict(db, p)
            if not v.hold:  # what settle does on a pass: the money now counts
                p.status = "succeeded"
                p.succeeded_at = now()
            await db.commit()
            return v.hold

    held = await asyncio.gather(_check(a.id), _check(b.id))
    assert sorted(held) == [False, True]
