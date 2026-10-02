"""A minimal in-loop ASGI WebSocket driver for the realtime tests.

Starlette's ``TestClient`` runs the app on its own thread and event loop, where the test's
async engine cannot follow; this driver runs the app as a task on the test's loop instead.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import MutableMapping
from types import TracebackType
from typing import Any

from fastapi import FastAPI

Message = dict[str, Any]


class WsSession:
    """One client socket against ``app`` at ``path``."""

    def __init__(self, app: FastAPI, path: str, *, ip: str = "203.0.113.7") -> None:
        self._app = app
        self._scope: Message = {
            "type": "websocket",
            "asgi": {"version": "3.0"},
            "scheme": "ws",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "headers": [(b"x-forwarded-for", ip.encode()), (b"host", b"test")],
            "client": (ip, 50000),
            "server": ("test", 80),
            "subprotocols": [],
        }
        self._to_app: asyncio.Queue[Message] = asyncio.Queue()
        self._from_app: asyncio.Queue[Message] = asyncio.Queue()
        self._task: asyncio.Task[None] | None = None
        self.close_code: int | None = None

    async def __aenter__(self) -> WsSession:
        await self._to_app.put({"type": "websocket.connect"})
        self._task = asyncio.create_task(self._app(self._scope, self._to_app.get, self._send))
        first = await asyncio.wait_for(self._from_app.get(), 5)
        if first["type"] == "websocket.close":
            self.close_code = int(first.get("code", 1000))
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self._to_app.put({"type": "websocket.disconnect", "code": 1000})
        if self._task is not None:
            try:
                await asyncio.wait_for(self._task, 5)
            except (TimeoutError, asyncio.CancelledError):
                self._task.cancel()

    async def _send(self, message: MutableMapping[str, Any]) -> None:
        await self._from_app.put(dict(message))

    async def send_json(self, data: object) -> None:
        await self._to_app.put({"type": "websocket.receive", "text": json.dumps(data)})

    async def receive(self, timeout: float = 3) -> Message | None:
        """The next JSON message, ``None`` once the app closed (``close_code`` is set)."""
        if self.close_code is not None:
            return None
        msg = await asyncio.wait_for(self._from_app.get(), timeout)
        if msg["type"] == "websocket.close":
            self.close_code = int(msg.get("code", 1000))
            return None
        return json.loads(msg["text"])

    async def receive_until_closed(self, timeout: float = 3) -> int:
        """Drain messages until the app closes the socket; the close code."""
        while await self.receive(timeout) is not None:
            pass
        assert self.close_code is not None
        return self.close_code
