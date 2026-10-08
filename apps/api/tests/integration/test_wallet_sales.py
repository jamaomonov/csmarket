# apps/api/tests/integration/test_wallet_sales.py
"""A sale on the ledger: credited once per sale, a rejected payout once per request."""

from __future__ import annotations

from decimal import Decimal

import pytest
from csmarket.core.ids import new_id
from csmarket.modules.wallet.api import (
    balance,
    credit_payout_return,
    credit_sale,
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
