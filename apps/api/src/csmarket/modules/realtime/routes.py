"""``WS /api/v1/realtime/orders`` — order nudges for the signed-in buyer (rulings R2, R3).

Protocol: the client opens the socket, then sends ``{"type": "auth", "token": <access
token>}`` within ``realtime_auth_timeout_seconds``. The server answers only with
``{"type": "order.changed", "number": …}``, ``{"type": "sale.updated", "number": …}`` and ``{"type": "ping"}`` (every
``realtime_ping_seconds``) and closes with 4401 on a bad, revoked or expired token — at the
latest when the token expires, so the client reconnects with a fresh one — and with 4429
past the ``ws-connect`` ip_guard bucket. Nothing secret travels in the URL. No database
session is held for the socket's life.
"""

from __future__ import annotations

import asyncio
import contextlib
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from csmarket.core.clock import now
from csmarket.core.config import get_settings
from csmarket.core.db import get_session_factory
from csmarket.core.errors import AccountSuspendedError, RateLimitedError, UnauthorizedError
from csmarket.core.logging import get_logger
from csmarket.core.metrics import ws_connected
from csmarket.modules.auth.api import AuthenticatedUser, authenticate, guard_ip
from csmarket.modules.realtime.registry import registry

router = APIRouter(prefix="/realtime", tags=["realtime"])
log = get_logger("csmarket.realtime.routes")

#: A close to a client already gone: Starlette's ``RuntimeError`` after a close, and its
#: ``WebSocketDisconnect`` for a send the server could not deliver (it wraps uvicorn's
#: ``ClientDisconnected``, an ``OSError``, which is listed too in case it ever leaks).
_GONE: tuple[type[Exception], ...] = (RuntimeError, WebSocketDisconnect, OSError)

#: Close codes the storefront reacts to.
CLOSE_UNAUTHORIZED = 4401
CLOSE_RATE_LIMITED = 4429


async def _who(ws: WebSocket, timeout: float) -> AuthenticatedUser | None:
    """The first frame's user, or ``None`` (bad frame, bad token, too slow, gone)."""
    try:
        raw = await asyncio.wait_for(ws.receive_text(), timeout)
        message = json.loads(raw)
    except (TimeoutError, WebSocketDisconnect, ValueError, KeyError, RuntimeError):
        return None
    if not isinstance(message, dict) or message.get("type") != "auth":
        return None
    token = message.get("token")
    if not isinstance(token, str) or not token:
        return None
    try:
        async with get_session_factory()() as db:
            return await authenticate(db, token)
    except (UnauthorizedError, AccountSuspendedError):
        return None


async def _ping(ws: WebSocket, every: float) -> None:
    while True:
        await asyncio.sleep(every)
        await ws.send_text('{"type":"ping"}')


async def _drain(ws: WebSocket) -> None:
    """Read and ignore client frames until the client goes away."""
    with contextlib.suppress(WebSocketDisconnect, RuntimeError):
        while True:
            await ws.receive_text()


async def _serve(ws: WebSocket, who: AuthenticatedUser, ping_every: float) -> int | None:
    """Run the socket until the client leaves or the token expires (→ the close code)."""
    remaining = max((who.expires_at - now()).total_seconds(), 0.0)
    drain = asyncio.create_task(_drain(ws))
    ping = asyncio.create_task(_ping(ws, ping_every))
    try:
        done, _ = await asyncio.wait(
            {drain, ping}, timeout=remaining, return_when=asyncio.FIRST_COMPLETED
        )
    finally:
        for task in (drain, ping):
            task.cancel()
        await asyncio.gather(drain, ping, return_exceptions=True)
    if drain in done:
        return None  # the client left
    return CLOSE_UNAUTHORIZED  # the token ran out (or a ping could not be sent)


@router.websocket("/orders")
async def orders_socket(ws: WebSocket) -> None:
    """Order nudges for the signed-in buyer; see the module docstring for the protocol."""
    settings = get_settings()
    await ws.accept()
    try:
        await guard_ip(ws, bucket="ws-connect")
    except RateLimitedError:
        with contextlib.suppress(*_GONE):
            await ws.close(code=CLOSE_RATE_LIMITED)
        return
    who = await _who(ws, settings.realtime_auth_timeout_seconds)
    if who is None:
        with contextlib.suppress(*_GONE):
            await ws.close(code=CLOSE_UNAUTHORIZED)
        return
    registry.add(who.user_id, ws)
    ws_connected(+1)
    try:
        code = await _serve(ws, who, settings.realtime_ping_seconds)
    finally:
        registry.remove(who.user_id, ws)
        ws_connected(-1)
    if code is not None:
        with contextlib.suppress(*_GONE):
            await ws.close(code=code)


__all__ = ["CLOSE_RATE_LIMITED", "CLOSE_UNAUTHORIZED", "router"]
