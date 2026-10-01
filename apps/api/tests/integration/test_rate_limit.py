"""Global per-IP rate limiting (slowapi). Off under ENVIRONMENT=test unless forced on."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from csmarket.core import config as cfg
from httpx import ASGITransport, AsyncClient

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def limited_client(db_engine, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[AsyncClient]:
    from csmarket.bootstrap import create_app
    from csmarket.core import db as core_db
    from csmarket.core import redis as core_redis
    from sqlalchemy.ext.asyncio import async_sessionmaker

    monkeypatch.setenv("CSMARKET_RATE_LIMIT_ENABLED", "true")
    monkeypatch.setenv("CSMARKET_RATE_LIMIT_DEFAULT", "3/minute")
    cfg.get_settings.cache_clear()
    core_db._engine = db_engine  # type: ignore[attr-defined]
    core_db._session_factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)  # type: ignore[attr-defined]
    core_redis._client = None  # type: ignore[attr-defined]
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    core_db._engine = None  # type: ignore[attr-defined]
    core_db._session_factory = None  # type: ignore[attr-defined]
    await core_redis.close_redis()
    cfg.get_settings.cache_clear()


async def test_request_over_limit_gets_429(limited_client: AsyncClient) -> None:
    # /openapi.json is the one non-exempt route M0 serves.
    for _ in range(3):
        assert (await limited_client.get("/openapi.json")).status_code == 200
    r = await limited_client.get("/openapi.json")
    assert r.status_code == 429
    assert "retry-after" in r.headers


async def test_health_probes_are_exempt(limited_client: AsyncClient) -> None:
    for _ in range(10):
        assert (await limited_client.get("/healthz")).status_code == 200
        assert (await limited_client.get("/readyz")).status_code == 200


async def test_rate_limit_off_by_default_in_tests(integration_client: AsyncClient) -> None:
    for _ in range(10):
        assert (await integration_client.get("/openapi.json")).status_code == 200
