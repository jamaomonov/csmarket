"""A user the admin blocked cannot start a kassa payment; the balance still pays."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from csmarket.core.ids import new_id
from csmarket.modules.users.models import User
from csmarket.modules.wallet.api import credit_topup
from httpx import AsyncClient, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.conftest import CUSTOMER_STEAM_ID, dev_login_headers
from tests.integration.orders_factory import make_order
from tests.integration.risk_factory import set_policy

pytestmark = pytest.mark.asyncio

PRICE = Decimal(171_800)


async def _buyer(c: AsyncClient, db: AsyncSession) -> tuple[dict[str, str], User]:
    headers = await dev_login_headers(c, steam_id=CUSTOMER_STEAM_ID, admin=False)
    user = await db.scalar(select(User).where(User.steam_id == CUSTOMER_STEAM_ID))
    assert user is not None
    return headers, user


async def _topup(c: AsyncClient, headers: dict[str, str], provider: str) -> Response:
    return await c.post(
        "/api/v1/wallet/topups",
        json={"amount_uzs": 50000, "provider": provider, "locale": "ru"},
        headers={**headers, "Idempotency-Key": f"topup-{uuid.uuid4()}"},
    )


async def _pay(c: AsyncClient, headers: dict[str, str], number: str, provider: str) -> Response:
    return await c.post(
        f"/api/v1/orders/{number}/pay",
        json={"provider": provider, "locale": "ru"},
        headers={**headers, "Idempotency-Key": f"pay-{uuid.uuid4()}"},
    )


@pytest.mark.parametrize("provider", ["payme", "p2p"])
async def test_a_blocked_user_cannot_open_a_topup(
    integration_client: AsyncClient, db_session: AsyncSession, provider: str
) -> None:
    headers, user = await _buyer(integration_client, db_session)
    await set_policy(db_session, user.id, kassa_blocked=True)
    r = await _topup(integration_client, headers, provider)
    assert (r.status_code, r.json()["code"]) == (403, "kassa_payment_blocked")


async def test_a_blocked_user_cannot_pay_an_order_in_a_kassa_but_the_balance_pays(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    headers, user = await _buyer(integration_client, db_session)
    await set_policy(db_session, user.id, kassa_blocked=True)
    order = await make_order(db_session, user=user, price_uzs=PRICE)
    blocked = await _pay(integration_client, headers, order.number, "mock")
    assert (blocked.status_code, blocked.json()["code"]) == (403, "kassa_payment_blocked")
    await credit_topup(
        db_session, user_id=user.id, topup_id=new_id(), amount=PRICE, provider="mock"
    )
    await db_session.commit()
    ok = await _pay(integration_client, headers, order.number, "wallet")
    assert ok.status_code == 200


async def test_an_unblocked_user_is_unaffected(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    headers, user = await _buyer(integration_client, db_session)
    await set_policy(db_session, user.id, kassa_blocked=False, trusted=False)
    order = await make_order(db_session, user=user, price_uzs=PRICE)
    r = await _pay(integration_client, headers, order.number, "mock")
    assert r.status_code == 200
