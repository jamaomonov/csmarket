"""``WS /api/v1/realtime/orders`` — first-message auth, one user's nudges, closes (M4b T2)."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from typing import Any

import pytest
from csmarket.core import config as cfg
from csmarket.core.ids import new_id
from csmarket.modules.auth import jwt as authjwt
from csmarket.modules.realtime import routes as realtime_routes
from csmarket.modules.realtime.api import CHANNEL
from csmarket.modules.realtime.listener import OrderEventsListener
from csmarket.modules.realtime.registry import registry
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.integration.conftest import dev_login_headers
from tests.integration.ws_kit import WsSession

PATH = "/api/v1/realtime/orders"


async def _signed_in(client: AsyncClient, steam_id: str) -> tuple[str, str]:
    """(user id, access token) for a fresh dev sign-in."""
    headers = await dev_login_headers(client, steam_id=steam_id, admin=False)
    me = await client.get("/api/v1/me", headers=headers)
    return me.json()["id"], headers["Authorization"].removeprefix("Bearer ")


async def _notify(engine: AsyncEngine, user_id: str, number: str) -> None:
    async with engine.begin() as conn:
        await conn.execute(
            text("SELECT pg_notify(:c, :p)"), {"c": CHANNEL, "p": f"{user_id}:{number}"}
        )


@pytest.fixture
async def listener(integration_client: AsyncClient) -> AsyncIterator[OrderEventsListener]:
    listen = OrderEventsListener(cfg.get_settings().database_url)
    await listen.start()
    assert await listen.wait_connected(5)
    yield listen
    await listen.stop()


async def _auth(ws: WsSession, token: str) -> None:
    await ws.send_json({"type": "auth", "token": token})


async def test_socket_receives_only_its_users_orders(
    integration_app: FastAPI,
    integration_client: AsyncClient,
    db_engine: AsyncEngine,
    listener: OrderEventsListener,
) -> None:
    a_id, a_token = await _signed_in(integration_client, "76561190000000101")
    b_id, _ = await _signed_in(integration_client, "76561190000000102")
    async with WsSession(integration_app, PATH) as ws:
        await _auth(ws, a_token)
        await _wait_registered(a_id)
        await _notify(db_engine, b_id, "B0000001")
        await _notify(db_engine, a_id, "A0000001")
        assert await ws.receive() == {"type": "order.changed", "number": "A0000001"}


async def test_bad_token_closes_4401(
    integration_app: FastAPI, integration_client: AsyncClient
) -> None:
    async with WsSession(integration_app, PATH) as ws:
        await _auth(ws, "nope")
        assert await ws.receive_until_closed() == 4401


async def test_no_auth_message_in_time_closes_4401(
    integration_app: FastAPI, integration_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _settings(monkeypatch, realtime_auth_timeout_seconds=0.2)
    async with WsSession(integration_app, PATH) as ws:
        assert await ws.receive_until_closed() == 4401


async def test_a_first_message_that_is_not_auth_closes_4401(
    integration_app: FastAPI, integration_client: AsyncClient
) -> None:
    async with WsSession(integration_app, PATH) as ws:
        await ws.send_json({"type": "hello"})
        assert await ws.receive_until_closed() == 4401


async def test_socket_closes_at_token_expiry(
    integration_app: FastAPI, integration_client: AsyncClient
) -> None:
    user_id, _ = await _signed_in(integration_client, "76561190000000103")
    short = cfg.get_settings().model_copy(update={"jwt_access_ttl_seconds": 2})
    token = authjwt.mint_access(sub=user_id, sid=new_id(), settings=short)
    async with WsSession(integration_app, PATH) as ws:
        await _auth(ws, token)
        assert await ws.receive_until_closed(timeout=6) == 4401
    assert registry.count(user_id) == 0


async def test_ping_every_interval(
    integration_app: FastAPI, integration_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _settings(monkeypatch, realtime_ping_seconds=0.2)
    _, token = await _signed_in(integration_client, "76561190000000104")
    async with WsSession(integration_app, PATH) as ws:
        await _auth(ws, token)
        assert await ws.receive() == {"type": "ping"}


async def test_disconnect_unregisters(
    integration_app: FastAPI, integration_client: AsyncClient
) -> None:
    user_id, token = await _signed_in(integration_client, "76561190000000105")
    async with WsSession(integration_app, PATH) as ws:
        await _auth(ws, token)
        await _wait_registered(user_id)
    await asyncio.sleep(0.1)
    assert registry.count(user_id) == 0


async def test_a_banned_user_cannot_connect(
    integration_app: FastAPI, integration_client: AsyncClient, db_engine: AsyncEngine
) -> None:
    user_id, token = await _signed_in(integration_client, "76561190000000106")
    async with db_engine.begin() as conn:
        await conn.execute(text("UPDATE users SET banned_at = now() WHERE id = :i"), {"i": user_id})
    async with WsSession(integration_app, PATH) as ws:
        await _auth(ws, token)
        assert await ws.receive_until_closed() == 4401


async def test_connect_bucket_closes_4429(
    integration_app: FastAPI, integration_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    limits = dict(cfg.get_settings().auth_ip_guard_bucket_max)
    limits["ws-connect"] = 2
    _settings(monkeypatch, auth_ip_guard_bucket_max=limits)
    codes = []
    for _ in range(3):
        async with WsSession(integration_app, PATH, ip="198.51.100.9") as ws:
            await _auth(ws, "nope")
            codes.append(await ws.receive_until_closed())
    assert codes == [4401, 4401, 4429]


async def test_the_listener_reconnects_after_its_connection_dies(
    integration_app: FastAPI,
    integration_client: AsyncClient,
    db_engine: AsyncEngine,
    listener: OrderEventsListener,
) -> None:
    user_id, token = await _signed_in(integration_client, "76561190000000107")
    async with db_engine.begin() as conn:
        await conn.execute(
            text(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE query LIKE 'LISTEN%' AND pid <> pg_backend_pid()"
            )
        )
    for _ in range(100):
        if listener.connections >= 2:
            break
        await asyncio.sleep(0.1)
    assert listener.connections >= 2
    assert await listener.wait_connected(5)
    async with WsSession(integration_app, PATH) as ws:
        await _auth(ws, token)
        await _wait_registered(user_id)
        await _notify(db_engine, user_id, "A0000002")
        assert await ws.receive(timeout=5) == {"type": "order.changed", "number": "A0000002"}


async def _wait_registered(user_id: str) -> None:
    for _ in range(50):
        if registry.count(user_id):
            return
        await asyncio.sleep(0.05)
    raise AssertionError("socket never registered")


def _settings(monkeypatch: pytest.MonkeyPatch, **update: Any) -> None:
    patched = cfg.get_settings().model_copy(update=update)
    getter: Callable[[], cfg.Settings] = lambda: patched  # noqa: E731
    monkeypatch.setattr(realtime_routes, "get_settings", getter)
    monkeypatch.setattr("csmarket.modules.auth.ip_guard.get_settings", getter)


async def test_no_log_line_carries_the_token_or_the_user(
    integration_app: FastAPI,
    integration_client: AsyncClient,
    db_engine: AsyncEngine,
    listener: OrderEventsListener,
    capsys: pytest.CaptureFixture[str],
) -> None:
    user_id, token = await _signed_in(integration_client, "76561190000000108")
    async with WsSession(integration_app, PATH) as ws:
        await _auth(ws, token)
        await _wait_registered(user_id)
        await _notify(db_engine, user_id, "A0000003")
        assert await ws.receive() is not None
    async with WsSession(integration_app, PATH) as ws:
        await _auth(ws, token + "x")
        await ws.receive_until_closed()
    out = capsys.readouterr()
    assert token not in out.out + out.err
    assert user_id not in out.out + out.err


async def test_a_client_gone_before_auth_ends_the_handler_quietly(
    integration_app: FastAPI, integration_client: AsyncClient
) -> None:
    async with WsSession(integration_app, PATH) as ws:
        await ws.leave()
        await ws.finished()  # the 4401 close to a gone client must not raise


async def test_a_silently_dead_socket_ends_on_the_next_ping(
    integration_app: FastAPI, integration_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _settings(monkeypatch, realtime_ping_seconds=0.1)
    user_id, token = await _signed_in(integration_client, "76561190000000108")
    async with WsSession(integration_app, PATH) as ws:
        await _auth(ws, token)
        await _wait_registered(user_id)
        ws.vanish()
        await ws.finished()  # the failed ping and the close after it must not raise
    assert registry.count(user_id) == 0
