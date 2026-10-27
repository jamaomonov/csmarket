"""A partner's reward on the ledger: ``referral_reward`` (spec 2026-10-27-referrals)."""

from __future__ import annotations

from decimal import Decimal

import pytest
from csmarket.core.errors import ConflictError
from csmarket.modules.wallet.api import (
    credit_referral_reward,
    entries_for_user,
    user_account,
    user_balance,
)
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.orders_factory import make_order
from tests.integration.payments_factory import make_user

pytestmark = pytest.mark.asyncio


async def test_credits_the_balance_once(db_session: AsyncSession) -> None:
    partner = await make_user(db_session)
    order = await make_order(db_session)
    first = await credit_referral_reward(
        db_session, user_id=partner.id, order_id=order.id, amount=Decimal(1718)
    )
    again = await credit_referral_reward(
        db_session, user_id=partner.id, order_id=order.id, amount=Decimal(1718)
    )
    assert again.id == first.id
    assert first.kind == "referral_reward"
    assert await user_balance(db_session, partner.id) == Decimal(1718)


async def test_customer_entry_has_no_order_number(db_session: AsyncSession) -> None:
    partner = await make_user(db_session)
    order = await make_order(db_session)
    await credit_referral_reward(
        db_session, user_id=partner.id, order_id=order.id, amount=Decimal(500)
    )
    page = await entries_for_user(db_session, partner.id)
    [line] = page.items
    assert line.kind == "referral_reward"
    assert line.amount == Decimal(500)
    assert line.reference_number is None


async def test_frozen_wallet_refuses(db_session: AsyncSession) -> None:
    partner = await make_user(db_session)
    order = await make_order(db_session)
    wallet = await user_account(db_session, partner.id)
    wallet.status = "frozen"
    await db_session.flush()
    with pytest.raises(ConflictError):
        await credit_referral_reward(
            db_session, user_id=partner.id, order_id=order.id, amount=Decimal(500)
        )
