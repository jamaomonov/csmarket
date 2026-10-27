"""A partner's reward on the ledger: ``referral_reward`` (spec 2026-10-27-referrals)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from decimal import Decimal

import pytest
from csmarket.core.errors import ConflictError
from csmarket.modules.users.models import User
from csmarket.modules.wallet.api import (
    credit_referral_reward,
    entries_for_user,
    user_account,
    user_balance,
)
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.conftest import CUSTOMER_STEAM_ID
from tests.integration.orders_factory import make_order
from tests.integration.payments_factory import make_user

pytestmark = pytest.mark.asyncio

Headers = Callable[[], Awaitable[dict[str, str]]]


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


async def test_the_histories_show_the_reward_over_http(
    db_session: AsyncSession,
    integration_client: AsyncClient,
    customer_headers: Headers,
    admin_headers: Headers,
) -> None:
    h = await customer_headers()
    partner = await db_session.scalar(select(User).where(User.steam_id == CUSTOMER_STEAM_ID))
    assert partner is not None
    partner_id = partner.id
    order = await make_order(db_session)
    await credit_referral_reward(
        db_session, user_id=partner_id, order_id=order.id, amount=Decimal(500)
    )
    await db_session.commit()
    r = await integration_client.get("/api/v1/wallet/entries", headers=h)
    assert r.status_code == 200, r.text
    [line] = r.json()["items"]
    assert (line["kind"], line["reference_number"]) == ("referral_reward", None)
    card = await integration_client.get(
        f"/api/v1/admin/users/{partner_id}", headers=await admin_headers()
    )
    assert card.status_code == 200, card.text
    assert [e["kind"] for e in card.json()["entries"]] == ["referral_reward"]
