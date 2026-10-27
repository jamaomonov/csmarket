"""``/referrals/me*``: a partner sees its terms, numbers and rewards — never the buyer."""

from __future__ import annotations

import base64
from collections.abc import Awaitable, Callable
from datetime import date, timedelta
from decimal import Decimal

import pytest
from csmarket.core.clock import now
from csmarket.modules.referrals.models import ReferralPartner, ReferralReward, ReferralVisitDay
from csmarket.modules.users.models import User
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.conftest import CUSTOMER_STEAM_ID
from tests.integration.payments_factory import make_user
from tests.integration.referrals_factory import attribute, make_partner, make_reward
from tests.integration.reviews_factory import delivered_order

pytestmark = pytest.mark.asyncio

Headers = Callable[[], Awaitable[dict[str, str]]]
ME = "/api/v1/referrals/me"


async def _me_partner(
    db: AsyncSession, customer_headers: Headers, **over: object
) -> tuple[dict[str, str], str]:
    h = await customer_headers()
    user = await db.scalar(select(User).where(User.steam_id == CUSTOMER_STEAM_ID))
    assert user is not None
    partner = await make_partner(db, user=user, code="me-partner", **over)
    return h, partner.user_id


async def test_not_a_partner_404(
    integration_client: AsyncClient, customer_headers: Headers
) -> None:
    h = await customer_headers()
    r = await integration_client.get(ME, headers=h)
    assert (r.status_code, r.json()["code"]) == (404, "not_a_partner")
    r = await integration_client.get(f"{ME}/rewards", headers=h)
    assert r.status_code == 404


async def test_signed_out_401(integration_client: AsyncClient) -> None:
    assert (await integration_client.get(ME)).status_code == 401


async def test_counts_this_month_and_all_time(
    db_session: AsyncSession, integration_client: AsyncClient, customer_headers: Headers
) -> None:
    h, pid = await _me_partner(db_session, customer_headers, percent=Decimal("2"))
    await make_partner(db_session, code="unused")  # someone else's numbers stay apart
    me = await db_session.get(ReferralPartner, pid)
    assert me is not None
    buyer = await make_user(db_session)
    await attribute(db_session, user=buyer, partner=me, at=now() - timedelta(days=400))
    old = await delivered_order(db_session, user=buyer, days_ago=200, price_uzs=Decimal(100_000))
    await make_reward(db_session, partner=me, order=old, status="credited")
    new = await delivered_order(db_session, user=buyer, days_ago=0.01, price_uzs=Decimal(50_000))
    await make_reward(db_session, partner=me, order=new)
    gone = await delivered_order(db_session, user=buyer, days_ago=0.02)
    await make_reward(db_session, partner=me, order=gone, status="cancelled")
    db_session.add(ReferralVisitDay(partner_id=pid, day=now().date(), visits=7))
    db_session.add(ReferralVisitDay(partner_id=pid, day=date(2025, 1, 1), visits=3))
    await db_session.commit()
    body = (await integration_client.get(ME, headers=h)).json()
    assert body["code"] == "me-partner"
    assert body["percent"] == "2.0"
    assert body["term_months"] == 6
    assert body["active"] is True
    assert body["all_time"] == {"visits": 10, "accounts": 1, "purchases": 2, "earned_uzs": "3000"}
    assert body["month"]["purchases"] == 1
    assert body["month"]["earned_uzs"] == "1000"
    assert body["held_uzs"] == "1000"
    assert body["credited_uzs"] == "2000"
    assert body["next_available_at"] is not None


async def test_inactive_partner_still_sees_the_page(
    db_session: AsyncSession, integration_client: AsyncClient, customer_headers: Headers
) -> None:
    h, _ = await _me_partner(db_session, customer_headers, active=False, term_months=None)
    body = (await integration_client.get(ME, headers=h)).json()
    assert body["active"] is False
    assert body["term_months"] is None
    assert body["next_available_at"] is None


async def test_rewards_carry_no_buyer(
    db_session: AsyncSession, integration_client: AsyncClient, customer_headers: Headers
) -> None:
    h, pid = await _me_partner(db_session, customer_headers)
    me = await db_session.get(ReferralPartner, pid)
    assert me is not None
    order = await delivered_order(db_session)
    await make_reward(db_session, partner=me, order=order)
    [item] = (await integration_client.get(f"{ME}/rewards", headers=h)).json()["items"]
    assert set(item) == {"delivered_at", "base_uzs", "amount_uzs", "status", "available_at"}


async def test_rewards_page_and_bad_cursor(
    db_session: AsyncSession, integration_client: AsyncClient, customer_headers: Headers
) -> None:
    h, pid = await _me_partner(db_session, customer_headers)
    me = await db_session.get(ReferralPartner, pid)
    assert me is not None
    for days in range(23):
        order = await delivered_order(db_session, days_ago=days + 1)
        await make_reward(db_session, partner=me, order=order)
    order_ids = {str(o) for o in (await db_session.scalars(select(ReferralReward.order_id))).all()}
    first = (await integration_client.get(f"{ME}/rewards", headers=h)).json()
    assert len(first["items"]) == 20
    token = first["next_cursor"]
    raw = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)).decode()
    assert not any(order_id in raw for order_id in order_ids)  # no order identity, even here
    second = (
        await integration_client.get(
            f"{ME}/rewards", params={"cursor": first["next_cursor"]}, headers=h
        )
    ).json()
    assert len(second["items"]) == 3
    assert second["next_cursor"] is None
    bad = await integration_client.get(f"{ME}/rewards", params={"cursor": "x"}, headers=h)
    assert bad.status_code == 422
