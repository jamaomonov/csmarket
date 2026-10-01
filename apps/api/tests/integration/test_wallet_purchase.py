"""``wallet.debit_purchase`` and ``wallet.credit_order_refund`` (rulings R8, R9): an order is
booked once from the balance, refunded once, and never drives the balance below zero."""

from __future__ import annotations

from decimal import Decimal

import pytest
from csmarket.core.errors import ConflictError
from csmarket.core.ids import new_id
from csmarket.modules.wallet.api import (
    InsufficientBalanceError,
    Leg,
    balance,
    credit_order_refund,
    credit_topup,
    debit_purchase,
    ensure_account,
    post,
    user_account,
    user_balance,
)
from csmarket.modules.wallet.models import WalletAccount, WalletPosting, WalletTransaction
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.payments_factory import make_user

PRICE = Decimal(171_800)


async def _funded(db: AsyncSession, amount: int) -> str:
    """A committed user with ``amount`` soʻm on the balance; their id."""
    user = await make_user(db)
    if amount:
        await credit_topup(
            db, user_id=user.id, topup_id=new_id(), amount=Decimal(amount), provider="mock"
        )
        await db.commit()
    return user.id


async def _legs(db: AsyncSession, txn: WalletTransaction) -> set[tuple[str, str, str, Decimal]]:
    """``(account kind, owner_id, direction, amount)`` of every leg of ``txn``."""
    rows = await db.execute(
        select(
            WalletAccount.kind,
            WalletAccount.owner_id,
            WalletPosting.direction,
            WalletPosting.amount,
        )
        .join(WalletAccount, WalletAccount.id == WalletPosting.account_id)
        .where(WalletPosting.transaction_id == txn.id)
    )
    return {(kind, owner, d, Decimal(a)) for kind, owner, d, a in rows.all()}


async def _count(db: AsyncSession, kind: str) -> int:
    stmt = select(func.count()).select_from(WalletTransaction).where(WalletTransaction.kind == kind)
    return int(await db.scalar(stmt) or 0)


async def test_a_purchase_debits_the_wallet_to_house_payments_received(
    db_session: AsyncSession,
) -> None:
    uid = await _funded(db_session, 500_000)
    order_id = new_id()
    txn = await debit_purchase(db_session, user_id=uid, order_id=order_id, amount=PRICE)
    await db_session.commit()
    assert (txn.kind, txn.idempotency_key) == ("purchase", f"purchase:order:{order_id}")
    assert (txn.reference_type, txn.reference_id, txn.actor) == ("order", order_id, "orders")
    assert await _legs(db_session, txn) == {
        ("user_wallet", uid, "C", PRICE),
        ("house_payments_received", "house", "D", PRICE),
    }
    assert await user_balance(db_session, uid) == Decimal(500_000) - PRICE


async def test_a_purchase_replay_returns_the_booked_transaction_before_the_balance_check(
    db_session: AsyncSession,
) -> None:
    """The whole balance is spent on the order; its replay still answers, without a 409."""
    uid = await _funded(db_session, int(PRICE))
    order_id = new_id()
    first = await debit_purchase(db_session, user_id=uid, order_id=order_id, amount=PRICE)
    await db_session.commit()
    again = await debit_purchase(db_session, user_id=uid, order_id=order_id, amount=PRICE)
    await db_session.commit()
    assert again.id == first.id
    assert await _count(db_session, "purchase") == 1
    assert await user_balance(db_session, uid) == 0


async def test_a_short_balance_is_balance_too_low_and_books_nothing(
    db_session: AsyncSession,
) -> None:
    uid = await _funded(db_session, int(PRICE) - 1)
    with pytest.raises(InsufficientBalanceError) as caught:
        await debit_purchase(db_session, user_id=uid, order_id=new_id(), amount=PRICE)
    assert caught.value.extra["code"] == "balance_too_low"
    assert caught.value.status_code == 409
    await db_session.rollback()
    assert await _count(db_session, "purchase") == 0
    assert await user_balance(db_session, uid) == PRICE - 1


async def test_a_user_without_a_wallet_has_nothing_to_spend(db_session: AsyncSession) -> None:
    uid = await _funded(db_session, 0)
    with pytest.raises(InsufficientBalanceError):
        await debit_purchase(db_session, user_id=uid, order_id=new_id(), amount=PRICE)
    await db_session.rollback()


async def test_a_purchase_key_used_by_another_kind_is_a_mismatch(db_session: AsyncSession) -> None:
    """Insurance: a refund booked under the purchase key is a caller bug, not a replay."""
    uid = await _funded(db_session, 500_000)
    order_id = new_id()
    wallet = await user_account(db_session, uid)
    house = await ensure_account(
        db_session, owner_type="house", owner_id="house", kind="house_payments_received"
    )
    await post(
        db_session,
        kind="refund",
        legs=[Leg(wallet.id, "D", PRICE), Leg(house.id, "C", PRICE)],
        idempotency_key=f"purchase:order:{order_id}",
    )
    with pytest.raises(ConflictError) as caught:
        await debit_purchase(db_session, user_id=uid, order_id=order_id, amount=PRICE)
    assert caught.value.extra["code"] == "idempotency_mismatch"
    await db_session.rollback()


async def test_a_balance_paid_refund_reverses_the_purchase_legs(db_session: AsyncSession) -> None:
    uid = await _funded(db_session, int(PRICE))
    order_id = new_id()
    await debit_purchase(db_session, user_id=uid, order_id=order_id, amount=PRICE)
    txn = await credit_order_refund(
        db_session, user_id=uid, order_id=order_id, amount=PRICE, paid_with="wallet"
    )
    await db_session.commit()
    assert (txn.kind, txn.idempotency_key) == ("refund", f"refund:order:{order_id}")
    assert (txn.reference_type, txn.reference_id, txn.actor) == ("order", order_id, "orders")
    assert await _legs(db_session, txn) == {
        ("user_wallet", uid, "D", PRICE),
        ("house_payments_received", "house", "C", PRICE),
    }
    assert await user_balance(db_session, uid) == PRICE
    house = await ensure_account(
        db_session, owner_type="house", owner_id="house", kind="house_payments_received"
    )
    assert await balance(db_session, house.id) == 0


@pytest.mark.parametrize("provider", ["click", "payme", "uzum", "mock"])
async def test_a_kassa_paid_refund_turns_the_kassa_money_into_balance(
    db_session: AsyncSession, provider: str
) -> None:
    """Ruling R9/H: D ``user_wallet`` / C ``provider_clearing:<provider>`` (a top-up's shape)."""
    uid = await _funded(db_session, 0)
    order_id = new_id()
    txn = await credit_order_refund(
        db_session, user_id=uid, order_id=order_id, amount=PRICE, paid_with=provider
    )
    await db_session.commit()
    assert await _legs(db_session, txn) == {
        ("user_wallet", uid, "D", PRICE),
        ("provider_clearing", provider, "C", PRICE),
    }
    clearing = await ensure_account(
        db_session, owner_type="provider", owner_id=provider, kind="provider_clearing"
    )
    assert await balance(db_session, clearing.id) == PRICE
    assert await user_balance(db_session, uid) == PRICE


async def test_a_refund_is_credited_once_under_its_key(db_session: AsyncSession) -> None:
    uid = await _funded(db_session, 0)
    order_id = new_id()
    first = await credit_order_refund(
        db_session, user_id=uid, order_id=order_id, amount=PRICE, paid_with="payme"
    )
    await db_session.commit()
    again = await credit_order_refund(
        db_session, user_id=uid, order_id=order_id, amount=PRICE, paid_with="payme"
    )
    await db_session.commit()
    assert again.id == first.id
    assert await _count(db_session, "refund") == 1
    assert await user_balance(db_session, uid) == PRICE


async def test_a_refund_names_its_actor(db_session: AsyncSession) -> None:
    """An admin's refund (Task 7) is booked as theirs."""
    uid = await _funded(db_session, 0)
    txn = await credit_order_refund(
        db_session,
        user_id=uid,
        order_id=new_id(),
        amount=PRICE,
        paid_with="click",
        actor="admin:a1",
    )
    await db_session.commit()
    assert txn.actor == "admin:a1"
