# apps/api/tests/unit/test_realtime_listener_kinds.py
"""The listener tells an order's nudge from a sale's by the payload's third part."""

from __future__ import annotations

import asyncio

from csmarket.modules.realtime.listener import OrderEventsListener


class _Target:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    async def publish(self, user_id: str, number: str, *, kind: str = "order") -> int:
        self.calls.append((user_id, number, kind))
        return 1


async def test_a_sale_payload_publishes_a_sale_update() -> None:
    target = _Target()
    listener = OrderEventsListener("postgresql+asyncpg://u@h/db", target=target)  # type: ignore[arg-type]
    listener._on_notify(None, 0, "order_events", "u1:S0000001:sale")
    listener._on_notify(None, 0, "order_events", "u1:A0000001")
    listener._on_notify(None, 0, "order_events", "garbage")
    await asyncio.sleep(0)
    assert target.calls == [("u1", "S0000001", "sale"), ("u1", "A0000001", "order")]
