"""Accounts carry their currency; a cross-currency leg pair is refused at post()."""

from __future__ import annotations

from decimal import Decimal

import pytest
from csmarket.core.errors import ValidationError
from csmarket.modules.wallet.api import Leg, ensure_account, post
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.payments_factory import make_user


async def test_accounts_get_the_currency_of_their_kind(db_session: AsyncSession) -> None:
    user = await make_user(db_session)
    uzs = await ensure_account(db_session, owner_type="user", owner_id=user.id, kind="user_wallet")
    usd = await ensure_account(
        db_session, owner_type="user", owner_id=user.id, kind="user_wallet_usd"
    )
    assert (uzs.currency, usd.currency) == ("UZS", "USD")


async def test_post_refuses_a_soum_debit_against_a_dollar_credit(db_session: AsyncSession) -> None:
    user = await make_user(db_session)
    uzs = await ensure_account(db_session, owner_type="user", owner_id=user.id, kind="user_wallet")
    usd = await ensure_account(
        db_session, owner_type="user", owner_id=user.id, kind="user_wallet_usd"
    )
    with pytest.raises(ValidationError, match="per currency"):
        await post(
            db_session,
            kind="admin_adjust",
            legs=[Leg(uzs.id, "D", Decimal(1000)), Leg(usd.id, "C", Decimal(1000))],
            idempotency_key="mixed-currency-test-0001",
        )
