"""Dev login (ruling P6): opens a session without Steam, never reachable in prod."""

from __future__ import annotations

import pytest
from csmarket.core import config as cfg
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

pytestmark = pytest.mark.asyncio


async def test_dev_login_opens_a_session_and_can_grant_admin(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    from csmarket.modules.users.service import get_user_by_steam_id

    r = await integration_client.post(
        "/api/v1/auth/dev-login",
        json={"steam_id": "76561198000000003", "display_name": "Dev", "admin": True},
    )
    assert r.status_code == 200
    assert r.json()["token_type"] == "Bearer"
    assert integration_client.cookies.get("csmarket_refresh")
    user = await get_user_by_steam_id(db_session, "76561198000000003")
    assert user is not None
    assert user.roles == ["admin"]
    assert user.display_name == "Dev"


async def test_dev_login_without_admin_grants_nothing(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    from csmarket.modules.users.service import get_user_by_steam_id

    r = await integration_client.post(
        "/api/v1/auth/dev-login", json={"steam_id": "76561198000000004"}
    )
    assert r.status_code == 200
    user = await get_user_by_steam_id(db_session, "76561198000000004")
    assert user is not None
    assert user.roles == []


async def test_dev_login_rejects_a_non_steam_id(integration_client: AsyncClient) -> None:
    r = await integration_client.post("/api/v1/auth/dev-login", json={"steam_id": "abc"})
    assert r.status_code == 422


async def test_dev_login_is_404_when_the_flag_is_off(
    integration_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CSMARKET_DEV_LOGIN_ENABLED", "false")
    cfg.get_settings.cache_clear()
    try:
        r = await integration_client.post(
            "/api/v1/auth/dev-login", json={"steam_id": "76561198000000003"}
        )
        assert r.status_code == 404
    finally:
        monkeypatch.undo()
        cfg.get_settings.cache_clear()


async def test_dev_login_is_not_in_the_openapi_schema(integration_client: AsyncClient) -> None:
    paths = (await integration_client.get("/openapi.json")).json()["paths"]
    assert "/api/v1/auth/dev-login" not in paths
    assert "/api/v1/auth/steam" in paths


async def test_prod_never_exposes_dev_login(
    monkeypatch: pytest.MonkeyPatch, db_engine: AsyncEngine
) -> None:
    from csmarket.bootstrap import create_app
    from httpx import ASGITransport

    monkeypatch.setenv("CSMARKET_ENVIRONMENT", "prod")
    monkeypatch.setenv("CSMARKET_DEV_LOGIN_ENABLED", "true")
    cfg.get_settings.cache_clear()
    try:
        app = create_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            r = await c.post("/api/v1/auth/dev-login", json={"steam_id": "76561198000000003"})
        assert r.status_code == 404
    finally:
        monkeypatch.undo()
        cfg.get_settings.cache_clear()
