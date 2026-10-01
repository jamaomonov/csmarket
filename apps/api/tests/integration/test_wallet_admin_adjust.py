"""``wallet.admin_adjust``: credit, clawback, never below zero (R13), one post per key."""

from __future__ import annotations

from decimal import Decimal

import pytest
from csmarket.core.errors import ConflictError, ValidationError
from csmarket.modules.wallet.api import (
    InsufficientBalanceError,
    admin_adjust,
    balance,
    ensure_account,
    entries_for_admin,
    entries_for_user,
    user_balance,
)
from csmarket.modules.wallet.models import WalletPosting, WalletTransaction
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.payments_factory import make_user

ADMIN_ID = "00000000-0000-4000-8000-000000000001"


async def _adjust(
    db: AsyncSession, user_id: str, amount: int, key: str, reason: str = "goodwill"
) -> WalletTransaction:
    return await admin_adjust(
        db,
        user_id=user_id,
        amount=Decimal(amount),
        reason=reason,
        admin_id=ADMIN_ID,
        idempotency_key=key,
    )


async def test_credit_then_clawback(db_session: AsyncSession) -> None:
    user = await make_user(db_session)
    credit = await _adjust(db_session, user.id, 5000, "adjust-key-credit-0001", "goodwill")
    await db_session.commit()
    assert await user_balance(db_session, user.id) == Decimal(5000)
    assert credit.kind == "admin_adjust"
    assert credit.idempotency_key == "admin_adjust:adjust-key-credit-0001"
    assert credit.actor == f"admin:{ADMIN_ID}"
    assert credit.extra_metadata == {"reason": "goodwill"}

    await _adjust(db_session, user.id, -2000, "adjust-key-claw-00001", "double credit")
    await db_session.commit()
    assert await user_balance(db_session, user.id) == Decimal(3000)
    house = await ensure_account(
        db_session, owner_type="house", owner_id="house", kind="house_adjustments"
    )
    # Contra account: D on a clawback, C on a credit — net 3 000 credited out of it.
    assert await balance(db_session, house.id) == Decimal(-3000)


async def test_clawback_below_zero_is_409(db_session: AsyncSession) -> None:
    uid = (await make_user(db_session)).id
    await _adjust(db_session, uid, 5000, "adjust-key-credit-0002")
    await db_session.commit()
    with pytest.raises(InsufficientBalanceError) as caught:
        await _adjust(db_session, uid, -6000, "adjust-key-claw-00002")
    assert caught.value.status_code == 409
    assert caught.value.extra["code"] == "balance_too_low"
    await db_session.rollback()
    assert await user_balance(db_session, uid) == Decimal(5000)


async def test_clawback_of_exactly_the_balance_reaches_zero(db_session: AsyncSession) -> None:
    user = await make_user(db_session)
    await _adjust(db_session, user.id, 5000, "adjust-key-credit-0003")
    await _adjust(db_session, user.id, -5000, "adjust-key-claw-00003")
    await db_session.commit()
    assert await user_balance(db_session, user.id) == Decimal(0)


async def test_clawback_with_no_wallet_is_409(db_session: AsyncSession) -> None:
    user = await make_user(db_session)
    with pytest.raises(InsufficientBalanceError):
        await _adjust(db_session, user.id, -1, "adjust-key-claw-00004")


async def test_replayed_adjust_posts_once(db_session: AsyncSession) -> None:
    user = await make_user(db_session)
    a = await _adjust(db_session, user.id, 7000, "adjust-key-same-0001")
    await db_session.commit()
    b = await _adjust(db_session, user.id, 7000, "adjust-key-same-0001")
    await db_session.commit()
    assert a.id == b.id
    assert await user_balance(db_session, user.id) == Decimal(7000)
    count = await db_session.scalar(
        select(func.count())
        .select_from(WalletTransaction)
        .where(WalletTransaction.kind == "admin_adjust")
    )
    assert count == 1


async def test_a_replayed_clawback_is_answered_before_the_balance_check(
    db_session: AsyncSession,
) -> None:
    user = await make_user(db_session)
    await _adjust(db_session, user.id, 5000, "adjust-key-credit-0005")
    first = await _adjust(db_session, user.id, -5000, "adjust-key-claw-00005")
    await db_session.commit()
    again = await _adjust(db_session, user.id, -5000, "adjust-key-claw-00005")
    assert again.id == first.id


@pytest.mark.parametrize(
    ("other_user", "amount"), [(False, 8000), (True, 7000)], ids=["amount", "user"]
)
async def test_a_reused_key_for_another_adjustment_is_409(
    db_session: AsyncSession, other_user: bool, amount: int
) -> None:
    user = await make_user(db_session)
    await _adjust(db_session, user.id, 7000, "adjust-key-reuse-0001")
    await db_session.commit()
    target = (await make_user(db_session)).id if other_user else user.id
    with pytest.raises(ConflictError) as caught:
        await _adjust(db_session, target, amount, "adjust-key-reuse-0001")
    assert caught.value.extra["code"] == "idempotency_mismatch"
    assert not isinstance(caught.value, InsufficientBalanceError)


@pytest.mark.parametrize(
    "amount",
    [Decimal(0), Decimal("0.5"), Decimal("100000001"), Decimal("-100000001"), Decimal("NaN")],
)
async def test_bad_amounts_are_refused(db_session: AsyncSession, amount: Decimal) -> None:
    user = await make_user(db_session)
    with pytest.raises(ValidationError):
        await admin_adjust(
            db_session,
            user_id=user.id,
            amount=amount,
            reason="goodwill",
            admin_id=ADMIN_ID,
            idempotency_key="adjust-key-bad-000001",
        )
    assert (await db_session.scalar(select(func.count()).select_from(WalletPosting))) == 0


async def test_the_largest_amount_is_accepted(db_session: AsyncSession) -> None:
    user = await make_user(db_session)
    await _adjust(db_session, user.id, 100_000_000, "adjust-key-max-000001")
    assert await user_balance(db_session, user.id) == Decimal(100_000_000)


async def test_a_blank_reason_is_refused(db_session: AsyncSession) -> None:
    user = await make_user(db_session)
    with pytest.raises(ValidationError):
        await _adjust(db_session, user.id, 1000, "adjust-key-blank-0001", reason="   ")


async def test_admin_entries_carry_actor_and_reason_customer_entries_do_not(
    db_session: AsyncSession,
) -> None:
    user = await make_user(db_session)
    await _adjust(db_session, user.id, 5000, "adjust-key-credit-0006", "goodwill")
    await _adjust(db_session, user.id, -1000, "adjust-key-claw-00006", "double credit")
    await db_session.commit()
    admin_view = await entries_for_admin(db_session, user.id)
    assert [(e.kind, e.amount, e.actor, e.reason) for e in admin_view] == [
        ("admin_adjust", Decimal(-1000), f"admin:{ADMIN_ID}", "double credit"),
        ("admin_adjust", Decimal(5000), f"admin:{ADMIN_ID}", "goodwill"),
    ]
    customer_view = (await entries_for_user(db_session, user.id)).items
    assert [e.id for e in customer_view] == [e.id for e in admin_view]
    assert not any(hasattr(e, "actor") or hasattr(e, "reason") for e in customer_view)


async def test_admin_entries_limit_and_no_wallet(db_session: AsyncSession) -> None:
    user = await make_user(db_session)
    assert await entries_for_admin(db_session, user.id) == []
    for i in range(3):
        await _adjust(db_session, user.id, 1000 + i, f"adjust-key-limit-000{i}")
    await db_session.commit()
    two = await entries_for_admin(db_session, user.id, limit=2)
    assert [e.amount for e in two] == [Decimal(1002), Decimal(1001)]


@pytest.mark.parametrize("limit", [0, 101])
async def test_entries_refuse_a_limit_out_of_range(db_session: AsyncSession, limit: int) -> None:
    user = await make_user(db_session)
    with pytest.raises(ValidationError):
        await entries_for_admin(db_session, user.id, limit=limit)
    with pytest.raises(ValidationError):
        await entries_for_user(db_session, user.id, limit=limit)
