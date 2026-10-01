"""``/api/v1/auth`` over HTTP: start redirect, Steam completion, refresh rotation, logout."""

from __future__ import annotations

import httpx
import pytest
import respx
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio
_OPENID = "https://steamcommunity.com/openid/login"


def _steam_params(sid: str = "76561198000000001") -> dict[str, str]:
    return {
        "openid.ns": "http://specs.openid.net/auth/2.0",
        "openid.mode": "id_res",
        "openid.claimed_id": f"https://steamcommunity.com/openid/id/{sid}",
        "openid.return_to": "http://localhost:3100/auth/steam/callback?locale=ru",
        "openid.sig": "s",
        "openid.signed": "a,b",
    }


async def test_start_redirects_to_steam_with_the_app_callback(
    integration_client: AsyncClient,
) -> None:
    r = await integration_client.get(
        "/api/v1/auth/steam/start", params={"app": "admin", "locale": "uz"}
    )
    assert r.status_code == 302
    loc = r.headers["location"]
    assert loc.startswith(_OPENID)
    assert "localhost%3A3102%2Fauth%2Fsteam%2Fcallback" in loc  # admin_base_url default
    assert "locale%3Duz" in loc


async def test_start_defaults_to_the_storefront(integration_client: AsyncClient) -> None:
    r = await integration_client.get("/api/v1/auth/steam/start")
    assert r.status_code == 302
    loc = r.headers["location"]
    assert "openid.realm=http%3A%2F%2Flocalhost%3A3100&" in loc
    assert "localhost%3A3100%2Fauth%2Fsteam%2Fcallback%3Flocale%3Dru" in loc


async def test_start_rejects_an_unknown_app(integration_client: AsyncClient) -> None:
    r = await integration_client.get(
        "/api/v1/auth/steam/start", params={"app": "https://evil.example"}
    )
    assert r.status_code == 422


@respx.mock
async def test_steam_post_sets_cookie_and_refresh_rotates_it(
    integration_client: AsyncClient,
) -> None:
    respx.post(_OPENID).mock(return_value=httpx.Response(200, text="is_valid:true\n"))
    r = await integration_client.post(
        "/api/v1/auth/steam", json={"app": "web", "params": _steam_params()}
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["token_type"] == "Bearer"
    assert "refresh_token" not in body
    set_cookie = r.headers["set-cookie"].lower()
    assert "httponly" in set_cookie
    first_cookie = integration_client.cookies.get("csmarket_refresh")
    assert first_cookie
    r2 = await integration_client.post("/api/v1/auth/refresh")
    assert r2.status_code == 200
    assert integration_client.cookies.get("csmarket_refresh") != first_cookie


@respx.mock
async def test_a_forged_callback_is_401_and_sets_no_cookie(
    integration_client: AsyncClient,
) -> None:
    respx.post(_OPENID).mock(return_value=httpx.Response(200, text="is_valid:false\n"))
    r = await integration_client.post(
        "/api/v1/auth/steam", json={"app": "web", "params": _steam_params()}
    )
    assert r.status_code == 401
    assert "set-cookie" not in r.headers


async def test_steam_post_rejects_unexpected_fields(integration_client: AsyncClient) -> None:
    r = await integration_client.post(
        "/api/v1/auth/steam",
        json={"app": "web", "params": _steam_params(), "return_to": "https://evil.example"},
    )
    assert r.status_code == 422


async def test_refresh_without_cookie_is_401(integration_client: AsyncClient) -> None:
    assert (await integration_client.post("/api/v1/auth/refresh")).status_code == 401


async def test_replaying_a_rotated_cookie_burns_the_session(
    integration_client: AsyncClient,
) -> None:
    r = await integration_client.post(
        "/api/v1/auth/dev-login", json={"steam_id": "76561198000000005"}
    )
    assert r.status_code == 200
    stale = integration_client.cookies.get("csmarket_refresh")
    assert (await integration_client.post("/api/v1/auth/refresh")).status_code == 200
    fresh = integration_client.cookies.get("csmarket_refresh")

    integration_client.cookies.set("csmarket_refresh", stale or "")
    assert (await integration_client.post("/api/v1/auth/refresh")).status_code == 401
    # The reuse trip-wire revoked the live session too, and that survived the 401.
    integration_client.cookies.set("csmarket_refresh", fresh or "")
    assert (await integration_client.post("/api/v1/auth/refresh")).status_code == 401


async def test_logout_clears_the_cookie(integration_client: AsyncClient) -> None:
    await integration_client.post("/api/v1/auth/dev-login", json={"steam_id": "76561198000000002"})
    r = await integration_client.post("/api/v1/auth/logout")
    assert r.status_code == 204
    assert integration_client.cookies.get("csmarket_refresh") is None
    assert (await integration_client.post("/api/v1/auth/refresh")).status_code == 401


async def test_logout_with_a_bearer_kills_the_access_token(
    integration_client: AsyncClient,
) -> None:
    from csmarket.core.redis import get_redis
    from csmarket.modules.auth.jwt import verify

    r = await integration_client.post(
        "/api/v1/auth/dev-login", json={"steam_id": "76561198000000006"}
    )
    access = r.json()["access_token"]
    out = await integration_client.post(
        "/api/v1/auth/logout", headers={"Authorization": f"Bearer {access}"}
    )
    assert out.status_code == 204
    assert await get_redis().get(f"auth:revoked:{verify(access).jti}") is not None


async def test_logout_without_any_session_is_still_204(integration_client: AsyncClient) -> None:
    r = await integration_client.post(
        "/api/v1/auth/logout", headers={"Authorization": "Bearer not-a-jwt"}
    )
    assert r.status_code == 204
