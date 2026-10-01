"""A banned account is refused at sign-in and on its very next request (Review Focus 4).

403 ``account-suspended``, never 401: a 401 would send the apps into a refresh loop.
"""

from __future__ import annotations

import httpx
import pytest
import respx
from csmarket.core.clock import now
from csmarket.modules.users.service import get_user_by_steam_id, upsert_user_by_steam
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio
_OPENID = "https://steamcommunity.com/openid/login"
_SID = "76561198000000010"


async def _ban(db: AsyncSession, steam_id: str) -> None:
    user = await get_user_by_steam_id(db, steam_id)
    if user is None:
        user = await upsert_user_by_steam(db, steam_id=steam_id, display_name=None, avatar_url=None)
    user.banned_at = now()
    user.ban_reason = "test"
    await db.commit()


@respx.mock
async def test_a_banned_account_cannot_sign_in_with_steam(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    respx.post(_OPENID).mock(return_value=httpx.Response(200, text="is_valid:true\n"))
    await _ban(db_session, _SID)
    params = {
        "openid.ns": "http://specs.openid.net/auth/2.0",
        "openid.mode": "id_res",
        "openid.claimed_id": f"https://steamcommunity.com/openid/id/{_SID}",
        "openid.return_to": "http://localhost:3100/auth/steam/callback?locale=ru",
        "openid.sig": "s",
        "openid.signed": "a,b",
    }
    r = await integration_client.post("/api/v1/auth/steam", json={"app": "web", "params": params})
    assert r.status_code == 403
    assert r.json()["type"].endswith("/account-suspended")
    assert "set-cookie" not in r.headers


async def test_a_ban_stops_the_very_next_refresh(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    r = await integration_client.post("/api/v1/auth/dev-login", json={"steam_id": _SID})
    assert r.status_code == 200
    await _ban(db_session, _SID)
    r2 = await integration_client.post("/api/v1/auth/refresh")
    assert r2.status_code == 403
    assert r2.json()["type"].endswith("/account-suspended")


async def test_a_banned_account_cannot_dev_login(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    await _ban(db_session, _SID)
    r = await integration_client.post("/api/v1/auth/dev-login", json={"steam_id": _SID})
    assert r.status_code == 403
