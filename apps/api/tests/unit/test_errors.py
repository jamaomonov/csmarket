"""RFC 7807 problem+json for every expected error."""

from __future__ import annotations

import httpx
import pytest
from csmarket.core.errors import (
    AppError,
    ConflictError,
    NotFoundError,
    RateLimitedError,
    UnauthorizedError,
    app_error_handler,
)
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

pytestmark = pytest.mark.asyncio


def _app() -> FastAPI:
    app = FastAPI()
    app.add_exception_handler(AppError, app_error_handler)  # type: ignore[arg-type]

    @app.get("/missing")
    async def missing() -> None:
        raise NotFoundError("no such order", order_number="7K3M9QX2")

    @app.get("/slow-down")
    async def slow_down() -> None:
        raise RateLimitedError(retry_after=30)

    @app.get("/dup")
    async def dup() -> None:
        raise ConflictError()

    @app.get("/who")
    async def who() -> None:
        raise UnauthorizedError()

    return app


async def _get(path: str) -> httpx.Response:
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        return await c.get(path)


async def test_problem_json_shape_and_extras() -> None:
    r = await _get("/missing")
    assert r.status_code == 404
    assert r.headers["content-type"] == "application/problem+json"
    body = r.json()
    assert body["type"] == "https://csmarket.uz/errors/not-found"
    assert body["title"] == "Not found"
    assert body["status"] == 404
    assert body["detail"] == "no such order"
    assert body["order_number"] == "7K3M9QX2"


async def test_default_detail_is_the_title() -> None:
    r = await _get("/dup")
    assert r.status_code == 409
    assert r.json()["detail"] == "Conflict"


async def test_retry_after_is_promoted_to_a_header() -> None:
    r = await _get("/slow-down")
    assert r.status_code == 429
    assert r.headers["retry-after"] == "30"
    assert r.json()["retry_after"] == 30


async def test_unauthorized_is_401() -> None:
    assert (await _get("/who")).status_code == 401
