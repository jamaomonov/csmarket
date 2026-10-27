"""``POST /referrals/visit``: a partner's link remembered for 30 days and counted once a day."""

from __future__ import annotations

import pytest
from csmarket.core import redis as core_redis
from csmarket.modules.referrals.models import ReferralVisitDay
from httpx import AsyncClient
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.referrals_factory import make_partner

pytestmark = pytest.mark.asyncio

URL = "/api/v1/referrals/visit"


def _ref_cookie(r_headers: list[tuple[str, str]]) -> list[str]:
    return [v for k, v in r_headers if k == "set-cookie" and v.startswith("csm_ref=")]


async def _visits(db: AsyncSession, partner_id: str) -> int:
    db.expire_all()
    rows = await db.scalars(
        select(ReferralVisitDay.visits).where(ReferralVisitDay.partner_id == partner_id)
    )
    return sum(rows.all())


async def test_active_code_sets_the_cookie_and_counts(
    db_session: AsyncSession, integration_client: AsyncClient
) -> None:
    partner = await make_partner(db_session, code="zufarmax")
    r = await integration_client.post(URL, json={"code": "zufarmax"})
    assert r.status_code == 204
    [cookie] = _ref_cookie(r.headers.multi_items())
    low = cookie.lower()
    assert "httponly" in low
    assert "samesite=lax" in low
    assert "max-age=2592000" in low
    assert integration_client.cookies.get("csm_ref") == "zufarmax"
    assert await _visits(db_session, partner.user_id) == 1


async def test_same_visitor_counts_once_a_day(
    db_session: AsyncSession, integration_client: AsyncClient
) -> None:
    partner = await make_partner(db_session, code="once-a-day")
    for _ in range(3):
        r = await integration_client.post(URL, json={"code": "once-a-day"})
        assert r.status_code == 204
    assert await _visits(db_session, partner.user_id) == 1


@pytest.mark.parametrize("code", ["nobody", "OFF-ONE", "x"])
async def test_unknown_or_inactive_code_sets_nothing(
    db_session: AsyncSession, integration_client: AsyncClient, code: str
) -> None:
    await make_partner(db_session, code="off-one", active=False)
    r = await integration_client.post(URL, json={"code": code})
    assert r.status_code == 204
    assert _ref_cookie(r.headers.multi_items()) == []


async def test_redis_down_still_204(
    db_session: AsyncSession, integration_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    partner = await make_partner(db_session, code="no-redis")

    def _down() -> object:
        raise RedisConnectionError("down")

    monkeypatch.setattr(core_redis, "get_redis", _down)
    r = await integration_client.post(URL, json={"code": "no-redis"})
    assert r.status_code == 204
    assert integration_client.cookies.get("csm_ref") == "no-redis"
    assert await _visits(db_session, partner.user_id) == 0
