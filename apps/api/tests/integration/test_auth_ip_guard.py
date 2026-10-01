"""``ip_guard`` end to end: 429 past the bucket limit, fail-open on Redis, no IP at rest."""

from __future__ import annotations

import pytest
from csmarket.core import config as cfg
from csmarket.core.redis import get_redis
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio

_IP = "203.0.113.77"
_PARAMS = {
    "openid.ns": "http://specs.openid.net/auth/2.0",
    "openid.mode": "id_res",
    # Not a Steam identity: refused (401) before any network call, after the guard.
    "openid.claimed_id": "https://evil.example/openid/id/1",
    "openid.return_to": "http://localhost:3100/auth/steam/callback?locale=ru",
    "openid.sig": "s",
    "openid.signed": "a,b",
}


async def _attempt(client: AsyncClient, ip: str = _IP) -> int:
    r = await client.post(
        "/api/v1/auth/steam",
        json={"app": "web", "params": _PARAMS},
        headers={"X-Forwarded-For": ip},
    )
    return r.status_code


async def test_steam_login_bucket_trips_with_retry_after(
    integration_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CSMARKET_AUTH_IP_GUARD_BUCKET_MAX", '{"steam-login": 3}')
    cfg.get_settings.cache_clear()
    try:
        statuses = [await _attempt(integration_client) for _ in range(3)]
        assert statuses == [401, 401, 401]
        r = await integration_client.post(
            "/api/v1/auth/steam",
            json={"app": "web", "params": _PARAMS},
            headers={"X-Forwarded-For": _IP},
        )
        assert r.status_code == 429
        assert r.headers["retry-after"] == str(cfg.get_settings().auth_ip_guard_window_seconds)
        # Another address has its own bucket.
        assert await _attempt(integration_client, "198.51.100.9") == 401
    finally:
        monkeypatch.undo()
        cfg.get_settings.cache_clear()


async def test_no_redis_key_holds_the_client_ip(integration_client: AsyncClient) -> None:
    await _attempt(integration_client)
    keys = [k async for k in get_redis().scan_iter("auth:ipguard:*")]
    assert keys, "the guard should have charged a counter"
    for k in keys:
        assert _IP not in (k.decode() if isinstance(k, bytes) else k)


async def test_redis_down_fails_open(
    integration_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from csmarket.modules.auth import ip_guard

    def broken() -> object:
        raise ConnectionError("redis is down")

    monkeypatch.setattr(ip_guard, "get_redis", broken)
    monkeypatch.setenv("CSMARKET_AUTH_IP_GUARD_BUCKET_MAX", '{"steam-login": 1}')
    cfg.get_settings.cache_clear()
    try:
        statuses = [await _attempt(integration_client) for _ in range(4)]
        assert 429 not in statuses
        assert set(statuses) == {401}
    finally:
        monkeypatch.undo()
        cfg.get_settings.cache_clear()
