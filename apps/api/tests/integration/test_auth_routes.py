"""``/api/v1/auth`` over HTTP: start redirect, Steam completion, refresh rotation, logout."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from urllib.parse import parse_qsl, urlsplit

import httpx
import pytest
import respx
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio
_OPENID = "https://steamcommunity.com/openid/login"


Assertion = Callable[..., dict[str, str]]
Begin = Callable[..., Awaitable[str]]
_OID = "csmarket_oid"


async def _users(db: AsyncSession) -> int:
    from csmarket.modules.users.models import User

    return (await db.execute(select(func.count()).select_from(User))).scalar_one()


def _oid_set_cookie(r: httpx.Response) -> str:
    """The ``Set-Cookie`` line for the sign-in nonce cookie."""
    lines = [v for k, v in r.headers.multi_items() if k == "set-cookie" and v.startswith(_OID)]
    assert len(lines) == 1, r.headers
    return lines[0]


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


async def test_start_binds_the_sign_in_to_this_browser(integration_client: AsyncClient) -> None:
    r = await integration_client.get("/api/v1/auth/steam/start")
    assert r.status_code == 302
    cookie = _oid_set_cookie(r).lower()
    assert "httponly" in cookie
    assert "samesite=lax" in cookie
    assert "max-age=600" in cookie
    assert "path=/api/v1/auth" in cookie
    nonce = integration_client.cookies.get(_OID)
    assert nonce
    assert len(nonce) >= 16
    return_to = dict(parse_qsl(urlsplit(r.headers["location"]).query))["openid.return_to"]
    assert dict(parse_qsl(urlsplit(return_to).query)) == {"locale": "ru", "n": nonce}


async def test_every_start_mints_a_fresh_nonce(integration_client: AsyncClient) -> None:
    await integration_client.get("/api/v1/auth/steam/start")
    first = integration_client.cookies.get(_OID)
    await integration_client.get("/api/v1/auth/steam/start")
    assert integration_client.cookies.get(_OID) != first


@respx.mock
async def test_a_post_without_the_nonce_cookie_is_401_and_writes_nothing(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    begin_steam: Begin,
    steam_assertion: Assertion,
) -> None:
    """Login CSRF: a victim handed the attacker's Steam redirect has no matching cookie."""
    route = respx.post(_OPENID).mock(return_value=httpx.Response(200, text="is_valid:true\n"))
    return_to = await begin_steam()
    integration_client.cookies.delete(_OID)
    r = await integration_client.post(
        "/api/v1/auth/steam", json={"app": "web", "params": steam_assertion(return_to)}
    )
    assert r.status_code == 401
    assert not route.called
    assert integration_client.cookies.get("csmarket_refresh") is None
    assert await _users(db_session) == 0


@respx.mock
async def test_a_post_with_another_browsers_nonce_is_401_and_writes_nothing(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    begin_steam: Begin,
    steam_assertion: Assertion,
) -> None:
    route = respx.post(_OPENID).mock(return_value=httpx.Response(200, text="is_valid:true\n"))
    attackers_return_to = await begin_steam()  # the attacker's own start…
    await begin_steam()  # …and the victim's, which holds a different nonce
    r = await integration_client.post(
        "/api/v1/auth/steam",
        json={"app": "web", "params": steam_assertion(attackers_return_to)},
    )
    assert r.status_code == 401
    assert not route.called
    assert integration_client.cookies.get("csmarket_refresh") is None
    assert integration_client.cookies.get(_OID) is None  # cleared on failure too
    assert await _users(db_session) == 0


@respx.mock
async def test_steam_post_sets_cookie_and_refresh_rotates_it(
    integration_client: AsyncClient, begin_steam: Begin, steam_assertion: Assertion
) -> None:
    respx.post(_OPENID).mock(return_value=httpx.Response(200, text="is_valid:true\n"))
    return_to = await begin_steam()
    r = await integration_client.post(
        "/api/v1/auth/steam", json={"app": "web", "params": steam_assertion(return_to)}
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["token_type"] == "Bearer"
    assert "refresh_token" not in body
    set_cookie = r.headers["set-cookie"].lower()
    assert "httponly" in set_cookie
    first_cookie = integration_client.cookies.get("csmarket_refresh")
    assert first_cookie
    assert integration_client.cookies.get(_OID) is None  # the nonce is single-use
    r2 = await integration_client.post("/api/v1/auth/refresh")
    assert r2.status_code == 200
    assert integration_client.cookies.get("csmarket_refresh") != first_cookie


@respx.mock
async def test_a_forged_callback_is_401_and_sets_no_session_cookie(
    integration_client: AsyncClient, begin_steam: Begin, steam_assertion: Assertion
) -> None:
    respx.post(_OPENID).mock(return_value=httpx.Response(200, text="is_valid:false\n"))
    return_to = await begin_steam()
    r = await integration_client.post(
        "/api/v1/auth/steam", json={"app": "web", "params": steam_assertion(return_to)}
    )
    assert r.status_code == 401
    assert "csmarket_refresh" not in r.headers.get("set-cookie", "")
    assert "max-age=0" in _oid_set_cookie(r).lower()  # the nonce is spent either way


async def test_steam_post_rejects_unexpected_fields(
    integration_client: AsyncClient, steam_assertion: Assertion
) -> None:
    r = await integration_client.post(
        "/api/v1/auth/steam",
        json={
            "app": "web",
            "params": steam_assertion("http://localhost:3100/auth/steam/callback"),
            "return_to": "https://evil.example",
        },
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


class _DeadRedis:
    """Every blocklist write fails, as during a Redis outage."""

    async def set(self, *_: object, **__: object) -> None:
        from redis.exceptions import ConnectionError as RedisConnectionError

        raise RedisConnectionError("redis is down")

    async def get(self, *_: object, **__: object) -> None:
        from redis.exceptions import ConnectionError as RedisConnectionError

        raise RedisConnectionError("redis is down")


async def test_refresh_reuse_and_logout_survive_a_redis_outage(
    integration_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The DB row is the source of truth; an unwritable blocklist must not 500 these."""
    from csmarket.modules.auth import service as svc

    r = await integration_client.post(
        "/api/v1/auth/dev-login", json={"steam_id": "76561198000000007"}
    )
    assert r.status_code == 200
    stale = integration_client.cookies.get("csmarket_refresh")
    monkeypatch.setattr(svc, "get_redis", _DeadRedis)

    assert (await integration_client.post("/api/v1/auth/refresh")).status_code == 200
    fresh = integration_client.cookies.get("csmarket_refresh")

    integration_client.cookies.set("csmarket_refresh", stale or "")
    assert (await integration_client.post("/api/v1/auth/refresh")).status_code == 401  # reuse

    integration_client.cookies.set("csmarket_refresh", fresh or "")
    assert (await integration_client.post("/api/v1/auth/logout")).status_code == 204
