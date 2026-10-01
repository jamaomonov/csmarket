"""Liveness and readiness probes."""

from __future__ import annotations

import pytest
from csmarket.core import health
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


async def test_healthz(client: AsyncClient) -> None:
    r = await client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


async def test_readyz_is_200_when_dependencies_answer(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def ok() -> bool:
        return True

    monkeypatch.setattr(health, "check_postgres", ok)
    monkeypatch.setattr(health, "check_redis", ok)
    r = await client.get("/readyz")
    assert r.status_code == 200
    assert r.json() == {"status": "ready", "checks": {"postgres": "ok", "redis": "ok"}}


async def test_readyz_is_503_when_a_dependency_fails(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review Focus 2: the deploy poll must not pass with the database down."""

    async def ok() -> bool:
        return True

    async def bad() -> bool:
        return False

    monkeypatch.setattr(health, "check_postgres", bad)
    monkeypatch.setattr(health, "check_redis", ok)
    r = await client.get("/readyz")
    assert r.status_code == 503
    assert r.json()["status"] == "degraded"
    assert r.json()["checks"]["postgres"] == "fail"


async def test_probes_are_never_cached(client: AsyncClient) -> None:
    r = await client.get("/healthz")
    assert r.headers["cache-control"] == "no-store"
