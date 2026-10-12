# apps/api/tests/integration/test_wallet_sales.py
"""A sale on the ledger: credited once per sale, a rejected payout once per request, an undone
rejection taken back once per undo."""

from __future__ import annotations

from decimal import Decimal

import pytest
from csmarket.core.ids import new_id
from csmarket.modules.wallet.api import (
    InsufficientBalanceError,
    balance,
    credit_payout_return,
    credit_sale,
    debit_payout_return,
    ensure_account,
    user_balance,
)
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.payments_factory import make_user

pytestmark = pytest.mark.asyncio


async def test_a_sale_is_credited_once_whatever_the_amount_of_a_replay(
    db_session: AsyncSession,
) -> None:
    user, sale_id = await make_user(db_session), new_id()
    first = await credit_sale(db_session, user_id=user.id, sale_id=sale_id, amount=Decimal(158_300))
    again = await credit_sale(db_session, user_id=user.id, sale_id=sale_id, amount=Decimal(999))
    await db_session.commit()
    assert again.id == first.id
    assert (first.kind, first.idempotency_key) == ("sale_credit", f"sale:{sale_id}")
    assert await user_balance(db_session, user.id) == Decimal(158_300)
    house = await ensure_account(
        db_session, owner_type="house", owner_id="house", kind="house_skin_buys"
    )
    assert await balance(db_session, house.id) == Decimal(158_300)


async def test_a_payout_return_is_keyed_by_its_request(db_session: AsyncSession) -> None:
    user, sale_id, request_id = await make_user(db_session), new_id(), new_id()
    txn = await credit_payout_return(
        db_session,
        user_id=user.id,
        sale_id=sale_id,
        request_id=request_id,
        amount=Decimal(155_200),
        actor="admin:x",
    )
    await credit_payout_return(
        db_session,
        user_id=user.id,
        sale_id=sale_id,
        request_id=request_id,
        amount=Decimal(155_200),
        actor="admin:x",
    )
    await db_session.commit()
    assert (txn.kind, txn.idempotency_key, txn.reference_type, txn.reference_id) == (
        "payout_return",
        f"payout_return:{request_id}",
        "sale",
        sale_id,
    )
    assert await user_balance(db_session, user.id) == Decimal(155_200)


async def test_an_undone_rejection_is_taken_back_once_and_never_below_zero(
    db_session: AsyncSession,
) -> None:
    user, sale_id, request_id = await make_user(db_session), new_id(), new_id()
    amount = Decimal(155_200)
    await credit_payout_return(
        db_session,
        user_id=user.id,
        sale_id=sale_id,
        request_id=request_id,
        amount=amount,
        actor="admin:x",
    )
    args = {"user_id": user.id, "sale_id": sale_id, "request_id": request_id, "actor": "admin:x"}
    first = await debit_payout_return(db_session, amount=amount, attempt=0, **args)
    again = await debit_payout_return(db_session, amount=amount, attempt=0, **args)
    assert again.id == first.id
    assert (first.kind, first.idempotency_key) == (
        "payout_return_reversal",
        f"payout_return_reversal:{request_id}:0",
    )
    assert await user_balance(db_session, user.id) == 0
    second = await credit_payout_return(db_session, amount=amount, attempt=1, **args)
    assert second.idempotency_key == f"payout_return:{request_id}:1"
    assert await user_balance(db_session, user.id) == amount
    with pytest.raises(InsufficientBalanceError) as caught:
        await debit_payout_return(db_session, amount=amount + 1, attempt=1, **args)
    assert caught.value.extra["code"] == "balance_spent"
