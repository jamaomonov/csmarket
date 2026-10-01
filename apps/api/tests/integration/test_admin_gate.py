"""The admin role gate: 401 without a token, 403 for a customer, live role checks."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

import pytest
from csmarket.modules.users.api import get_user_by_steam_id, set_roles
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio
Headers = Callable[[], Awaitable[dict[str, str]]]
#: The account ``admin_headers`` signs in as (``conftest.ADMIN_STEAM_ID``).
ADMIN_STEAM_ID = "76561198000000009"


async def test_no_token_is_401(integration_client: AsyncClient) -> None:
    assert (await integration_client.get("/api/v1/admin/me")).status_code == 401


async def test_customer_is_403(integration_client: AsyncClient, customer_headers: Headers) -> None:
    r = await integration_client.get("/api/v1/admin/me", headers=await customer_headers())
    assert r.status_code == 403


async def test_admin_gets_their_profile(
    integration_client: AsyncClient, admin_headers: Headers
) -> None:
    r = await integration_client.get("/api/v1/admin/me", headers=await admin_headers())
    assert r.status_code == 200
    assert "admin" in r.json()["roles"]


async def test_role_removal_takes_effect_on_the_next_request(
    integration_client: AsyncClient, db_session: AsyncSession, admin_headers: Headers
) -> None:
    headers = await admin_headers()
    user = await get_user_by_steam_id(db_session, ADMIN_STEAM_ID)
    assert user is not None
    await set_roles(db_session, user, [])
    await db_session.commit()
    assert (await integration_client.get("/api/v1/admin/me", headers=headers)).status_code == 403
