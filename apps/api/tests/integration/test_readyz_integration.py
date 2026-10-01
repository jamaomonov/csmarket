"""``/readyz`` against a real Postgres and Redis (Review Focus 2)."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


async def test_readyz_is_200_against_live_dependencies(integration_client: AsyncClient) -> None:
    r = await integration_client.get("/readyz")
    assert r.status_code == 200, r.text
    assert r.json() == {"status": "ready", "checks": {"postgres": "ok", "redis": "ok"}}


async def test_readyz_is_503_when_redis_is_unreachable(
    integration_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from csmarket.core import config as cfg
    from csmarket.core import redis as core_redis

    core_redis._client = None  # type: ignore[attr-defined]
    monkeypatch.setenv("CSMARKET_REDIS_URL", "redis://127.0.0.1:1/0")
    cfg.get_settings.cache_clear()
    try:
        r = await integration_client.get("/readyz")
        assert r.status_code == 503
        assert r.json()["checks"] == {"postgres": "ok", "redis": "fail"}
    finally:
        core_redis._client = None  # type: ignore[attr-defined]
        monkeypatch.undo()
        cfg.get_settings.cache_clear()
