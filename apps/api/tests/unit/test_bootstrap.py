"""Composition root: CORS posture, docs exposure, metrics, prod-config warning."""

from __future__ import annotations

from typing import Any, cast

import pytest
from csmarket.bootstrap import create_app, missing_prod_settings
from csmarket.core.config import Settings
from httpx import ASGITransport, AsyncClient
from starlette.middleware.cors import CORSMiddleware


def _cors_kwargs(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    monkeypatch.setattr("csmarket.bootstrap.get_settings", lambda: settings)
    app = create_app()
    for middleware in app.user_middleware:
        if cast(object, middleware.cls) is CORSMiddleware:
            return dict(middleware.kwargs)
    raise AssertionError("CORSMiddleware was not registered")


def test_wildcard_cors_reflects_origin_only_outside_prod(monkeypatch: pytest.MonkeyPatch) -> None:
    kwargs = _cors_kwargs(Settings(environment="dev", cors_allow_origins=["*"]), monkeypatch)
    assert kwargs["allow_origin_regex"] == ".*"
    assert kwargs["allow_credentials"] is True


def test_wildcard_cors_is_stripped_in_prod(monkeypatch: pytest.MonkeyPatch) -> None:
    kwargs = _cors_kwargs(
        Settings(environment="prod", cors_allow_origins=["*", "https://csmarket.uz"]), monkeypatch
    )
    assert "allow_origin_regex" not in kwargs
    assert kwargs["allow_origins"] == ["https://csmarket.uz"]


def test_explicit_origins_are_passed_through(monkeypatch: pytest.MonkeyPatch) -> None:
    kwargs = _cors_kwargs(
        Settings(
            environment="prod",
            cors_allow_origins=["https://csmarket.uz", "https://admin.csmarket.uz"],
        ),
        monkeypatch,
    )
    assert kwargs["allow_origins"] == ["https://csmarket.uz", "https://admin.csmarket.uz"]


async def test_openapi_and_docs_are_off_in_prod(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("csmarket.bootstrap.get_settings", lambda: Settings(environment="prod"))
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        assert (await c.get("/openapi.json")).status_code == 404
        assert (await c.get("/docs")).status_code == 404


async def test_openapi_is_on_outside_prod(client: AsyncClient) -> None:
    r = await client.get("/openapi.json")
    assert r.status_code == 200
    assert r.json()["info"]["title"] == "csmarket API"
    assert "/healthz" in r.json()["paths"]


async def test_metrics_endpoint_is_exposed_but_not_documented(client: AsyncClient) -> None:
    r = await client.get("/metrics")
    assert r.status_code == 200
    assert "http_requests_total" in r.text or "http_request_duration_seconds" in r.text
    assert "/metrics" not in (await client.get("/openapi.json")).json()["paths"]


def test_missing_prod_settings_is_empty_outside_prod() -> None:
    assert missing_prod_settings(Settings(environment="dev")) == []


def test_missing_prod_settings_lists_nothing_in_m0() -> None:
    """The tuple is empty until M1/M3 add JWT keys and acquirer credentials."""
    assert missing_prod_settings(Settings(environment="prod")) == []
