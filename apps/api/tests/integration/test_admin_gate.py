"""The admin role gate: 401 without a token, 403 for a customer, live role checks."""

from __future__ import annotations

import pytest
from csmarket.modules.users.api import get_user_by_steam_id, set_roles
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio


async def _token(c: AsyncClient, *, admin: bool) -> dict[str, str]:
    sid = "76561198000000009" if admin else "76561198000000008"
    r = await c.post("/api/v1/auth/dev-login", json={"steam_id": sid, "admin": admin})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def test_no_token_is_401(integration_client: AsyncClient) -> None:
    assert (await integration_client.get("/api/v1/admin/me")).status_code == 401


async def test_customer_is_403(integration_client: AsyncClient) -> None:
    headers = await _token(integration_client, admin=False)
    r = await integration_client.get("/api/v1/admin/me", headers=headers)
    assert r.status_code == 403


async def test_admin_gets_their_profile(integration_client: AsyncClient) -> None:
    headers = await _token(integration_client, admin=True)
    r = await integration_client.get("/api/v1/admin/me", headers=headers)
    assert r.status_code == 200
    assert "admin" in r.json()["roles"]


async def test_role_removal_takes_effect_on_the_next_request(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    headers = await _token(integration_client, admin=True)
    user = await get_user_by_steam_id(db_session, "76561198000000009")
    assert user is not None
    await set_roles(db_session, user, [])
    await db_session.commit()
    assert (await integration_client.get("/api/v1/admin/me", headers=headers)).status_code == 403
