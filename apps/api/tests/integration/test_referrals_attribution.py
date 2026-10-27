"""An account is tied to the partner whose link it came by — at its first sign-in only."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

import httpx
import pytest
import respx
from csmarket.core.config import Settings
from csmarket.modules.auth.service import steam_login
from csmarket.modules.referrals.models import ReferralAttribution
from csmarket.modules.users.service import sign_in_by_steam
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.referrals_factory import make_partner

pytestmark = pytest.mark.asyncio

WEB = Settings(
    environment="test",
    web_base_url="https://csmarket.uz",
    admin_base_url="https://admin.csmarket.uz",
)
SID = "76561198000000555"
_OPENID = "https://steamcommunity.com/openid/login"

Assertion = Callable[..., dict[str, str]]
Begin = Callable[..., Awaitable[str]]


async def _verified(params: dict[str, str], **_: object) -> int:
    return int(SID)


async def _attribution(db: AsyncSession) -> ReferralAttribution | None:
    db.expire_all()
    return await db.scalar(select(ReferralAttribution))


async def _login(db: AsyncSession, *, ref: str | None, app: str = "web") -> None:
    await steam_login(
        db,
        {},
        app=app,  # type: ignore[arg-type]  # the two apps are the literal's values
        nonce="n",
        settings=WEB,
        verifier=_verified,
        ref_code=ref,
    )
    await db.commit()


async def test_new_account_with_cookie_is_attributed(db_session: AsyncSession) -> None:
    partner_id = (await make_partner(db_session, code="zufarmax")).user_id
    await _login(db_session, ref="zufarmax")
    row = await _attribution(db_session)
    assert row is not None
    assert row.partner_id == partner_id


async def test_existing_account_is_not_attributed(db_session: AsyncSession) -> None:
    await make_partner(db_session, code="zufarmax")
    await sign_in_by_steam(db_session, steam_id=SID, display_name=None, avatar_url=None)
    await db_session.commit()
    await _login(db_session, ref="zufarmax")
    assert await _attribution(db_session) is None


async def test_admin_app_never_attributes(db_session: AsyncSession) -> None:
    await make_partner(db_session, code="zufarmax")
    await _login(db_session, ref="zufarmax", app="admin")
    assert await _attribution(db_session) is None


async def test_inactive_partner_cookie_ignored(db_session: AsyncSession) -> None:
    await make_partner(db_session, code="sleepy", active=False)
    await _login(db_session, ref="sleepy")
    assert await _attribution(db_session) is None


async def test_unknown_code_ignored(db_session: AsyncSession) -> None:
    await _login(db_session, ref="ghost")
    assert await _attribution(db_session) is None


@respx.mock
async def test_cookie_carried_through_the_route_and_cleared(
    db_session: AsyncSession,
    integration_client: AsyncClient,
    begin_steam: Begin,
    steam_assertion: Assertion,
) -> None:
    respx.post(_OPENID).mock(return_value=httpx.Response(200, text="is_valid:true\n"))
    partner_id = (await make_partner(db_session, code="via-route")).user_id
    await integration_client.post("/api/v1/referrals/visit", json={"code": "via-route"})
    assert integration_client.cookies.get("csm_ref") == "via-route"
    return_to = await begin_steam()
    r = await integration_client.post(
        "/api/v1/auth/steam", json={"app": "web", "params": steam_assertion(return_to)}
    )
    assert r.status_code == 200, r.text
    assert integration_client.cookies.get("csm_ref") is None
    row = await _attribution(db_session)
    assert row is not None
    assert row.partner_id == partner_id


async def test_cookie_cleared_on_refusal(
    db_session: AsyncSession,
    integration_client: AsyncClient,
    begin_steam: Begin,
    steam_assertion: Assertion,
) -> None:
    await make_partner(db_session, code="refused")
    await integration_client.post("/api/v1/referrals/visit", json={"code": "refused"})
    assert integration_client.cookies.get("csm_ref") == "refused"
    return_to = await begin_steam()
    integration_client.cookies.delete("csmarket_oid")  # not this browser's sign-in → 401
    r = await integration_client.post(
        "/api/v1/auth/steam", json={"app": "web", "params": steam_assertion(return_to)}
    )
    assert r.status_code == 401
    assert integration_client.cookies.get("csm_ref") is None
