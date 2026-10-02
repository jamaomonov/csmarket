"""The sockets this API process holds, by user (ruling R1).

In-process on purpose: one uvicorn process per API container (AGENTS §11), and every
process runs its own Postgres listener, so each serves exactly the sockets it accepted.
"""

from __future__ import annotations

import json
from typing import Protocol

from csmarket.core.logging import get_logger
from csmarket.core.metrics import record_ws_nudges

log = get_logger("csmarket.realtime.registry")


class Socket(Protocol):
    """What the registry needs of a socket."""

    async def send_text(self, data: str) -> None:
        """Send one text frame."""


class Registry:
    """``user_id → sockets``; a socket that fails to send is dropped."""

    def __init__(self) -> None:
        self._sockets: dict[str, set[Socket]] = {}

    def add(self, user_id: str, socket: Socket) -> None:
        """Start delivering ``user_id``'s nudges to ``socket``."""
        self._sockets.setdefault(user_id, set()).add(socket)

    def remove(self, user_id: str, socket: Socket) -> None:
        """Stop delivering to ``socket``. Idempotent."""
        sockets = self._sockets.get(user_id)
        if sockets is None:
            return
        sockets.discard(socket)
        if not sockets:
            del self._sockets[user_id]

    def count(self, user_id: str) -> int:
        """How many sockets ``user_id`` has open here."""
        return len(self._sockets.get(user_id, ()))

    async def publish(self, user_id: str, number: str) -> int:
        """Send ``{"type": "order.changed", "number": …}`` to every socket of ``user_id``.

        Returns:
            How many sockets it reached.
        """
        frame = json.dumps({"type": "order.changed", "number": number}, separators=(",", ":"))
        reached = 0
        for socket in list(self._sockets.get(user_id, ())):
            try:
                await socket.send_text(frame)
            except Exception as exc:  # noqa: BLE001 -- a dead socket must not stop the others
                log.info("realtime.socket_dropped", error=type(exc).__name__)
                self.remove(user_id, socket)
                continue
            reached += 1
        record_ws_nudges(reached)
        return reached


#: The process's registry.
registry = Registry()

__all__ = ["Registry", "Socket", "registry"]
