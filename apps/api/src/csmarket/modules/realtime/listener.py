"""One Postgres ``LISTEN order_events`` connection per API process (ruling R1).

Reconnects with backoff (1 s → 30 s) and never raises out of its task: a lost listener
degrades the order page to polling, which stays the reconciler anyway.
"""

from __future__ import annotations

import asyncio
import contextlib

import asyncpg  # type: ignore[import-untyped]  # no bundled stubs

from csmarket.core.logging import get_logger
from csmarket.modules.realtime.api import CHANNEL
from csmarket.modules.realtime.registry import Registry, registry

log = get_logger("csmarket.realtime.listener")

_BACKOFF_START = 1.0
_BACKOFF_CAP = 30.0
_CHECK_SECONDS = 1.0


def _raw_dsn(url: str) -> str:
    """SQLAlchemy's ``postgresql+asyncpg://`` URL as a bare asyncpg DSN."""
    return url.replace("postgresql+asyncpg://", "postgresql://")


class OrderEventsListener:
    """Holds the LISTEN connection and hands each nudge to the registry."""

    def __init__(self, database_url: str, *, target: Registry = registry) -> None:
        self._dsn = _raw_dsn(database_url)
        self._target = target
        self._task: asyncio.Task[None] | None = None
        self._conn: asyncpg.Connection | None = None
        self._connected = asyncio.Event()
        self._sends: set[asyncio.Task[int]] = set()
        self.connections = 0

    async def start(self) -> None:
        """Start listening in the background."""
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="realtime-listener")

    async def stop(self) -> None:
        """Stop listening and close the connection."""
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        await self._close()

    async def wait_connected(self, timeout: float) -> bool:
        """Whether the connection is up within ``timeout`` seconds."""
        try:
            await asyncio.wait_for(self._connected.wait(), timeout)
        except TimeoutError:
            return False
        return True

    async def _run(self) -> None:
        delay = _BACKOFF_START
        while True:
            try:
                conn = await asyncpg.connect(self._dsn)
                await conn.add_listener(CHANNEL, self._on_notify)
            except Exception as exc:  # noqa: BLE001 -- degrade to polling, retry later
                log.warning("realtime.listen_failed", error=type(exc).__name__)
                await asyncio.sleep(delay)
                delay = min(delay * 2, _BACKOFF_CAP)
                continue
            self._conn = conn
            self.connections += 1
            self._connected.set()
            delay = _BACKOFF_START
            log.info("realtime.listening")
            while not conn.is_closed():
                await asyncio.sleep(_CHECK_SECONDS)
            self._connected.clear()
            self._conn = None
            log.warning("realtime.listener_lost")

    def _on_notify(self, _conn: object, _pid: int, _channel: str, payload: str) -> None:
        """asyncpg's callback: ``user_id:number`` (an order) or ``user_id:number:sale``."""
        user_id, sep, rest = payload.partition(":")
        number, _, kind = rest.partition(":")
        if not sep or not user_id or not number:
            return
        send = asyncio.create_task(
            self._target.publish(user_id, number, kind="sale" if kind == "sale" else "order")
        )
        self._sends.add(send)
        send.add_done_callback(self._sends.discard)

    async def _close(self) -> None:
        conn, self._conn = self._conn, None
        self._connected.clear()
        if conn is not None and not conn.is_closed():
            with contextlib.suppress(Exception):
                await conn.close()


__all__ = ["OrderEventsListener"]
