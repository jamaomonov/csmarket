"""Shared set-up for the desk tests: the owner's headers (``admin`` + ``desk``), deals."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import pytest
from csmarket.modules.users.api import get_user_by_steam_id, set_roles
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.conftest import ADMIN_STEAM_ID, dev_login_headers

Headers = Callable[[], Awaitable[dict[str, str]]]
BASE = "/api/v1/admin/desk"
LINK = "https://steamcommunity.com/tradeoffer/new/?partner=39734273&token=AbCdEf12"
REDLINE = "AK-47 | Redline (Field-Tested)"
ASIIMOV = "AWP | Asiimov (Field-Tested)"
_n = {"key": 0}


def key() -> dict[str, str]:
    """A fresh ``Idempotency-Key`` header."""
    _n["key"] += 1
    return {"Idempotency-Key": f"desk-test-key-{_n['key']:08d}"}


@pytest.fixture
def desk_headers(integration_client: AsyncClient, db_session: AsyncSession) -> Headers:
    """``await desk_headers()`` — the owner signed in with ``admin`` and ``desk``."""

    async def _headers() -> dict[str, str]:
        headers = await dev_login_headers(integration_client, steam_id=ADMIN_STEAM_ID, admin=True)
        user = await get_user_by_steam_id(db_session, ADMIN_STEAM_ID)
        assert user is not None
        if "desk" not in user.roles:
            await set_roles(db_session, user, [*user.roles, "desk"])
            await db_session.commit()
        return headers

    return _headers


def deal_body(**over: Any) -> dict[str, Any]:
    """Two skins for Skinslink (800 $ + 400 $), no price yet."""
    body: dict[str, Any] = {
        "trader": "trader one",
        "trade_link": LINK,
        "items": [
            {
                "name": REDLINE,
                "asset_id": "100",
                "skinslink_usd": "800",
                "destination": "skinslink",
            },
            {
                "name": ASIIMOV,
                "asset_id": "101",
                "skinslink_usd": "400",
                "destination": "skinslink",
            },
        ],
    }
    body.update(over)
    return body


async def create(c: AsyncClient, headers: dict[str, str], **over: Any) -> dict[str, Any]:
    """POST a deal; its JSON."""
    r = await c.post(f"{BASE}/deals", json=deal_body(**over), headers=headers | key())
    assert r.status_code == 201, r.text
    out: dict[str, Any] = r.json()
    return out
