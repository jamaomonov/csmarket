"""``realtime.registry.Registry``: a user's sockets, fan-out, dead sockets dropped."""

from __future__ import annotations

from csmarket.modules.realtime.registry import Registry


class _Socket:
    def __init__(self, *, broken: bool = False) -> None:
        self.sent: list[str] = []
        self.broken = broken

    async def send_text(self, data: str) -> None:
        if self.broken:
            raise RuntimeError("closed")
        self.sent.append(data)


async def test_publish_reaches_every_socket_of_the_user_only() -> None:
    reg = Registry()
    a1, a2, b = _Socket(), _Socket(), _Socket()
    reg.add("a", a1)
    reg.add("a", a2)
    reg.add("b", b)
    assert await reg.publish("a", "A0000001") == 2
    assert a1.sent == a2.sent == ['{"type":"order.changed","number":"A0000001"}']
    assert b.sent == []


async def test_a_socket_that_fails_to_send_is_dropped() -> None:
    reg = Registry()
    good, bad = _Socket(), _Socket(broken=True)
    reg.add("a", good)
    reg.add("a", bad)
    assert await reg.publish("a", "A0000001") == 1
    assert reg.count("a") == 1


async def test_remove_forgets_an_empty_user() -> None:
    reg = Registry()
    s = _Socket()
    reg.add("a", s)
    reg.remove("a", s)
    reg.remove("a", s)
    assert reg.count("a") == 0
    assert await reg.publish("a", "A0000001") == 0


async def test_a_sale_nudge_says_sale_updated() -> None:
    reg = Registry()
    socket = _Socket()
    reg.add("a", socket)
    assert await reg.publish("a", "S0000001", kind="sale") == 1
    assert socket.sent == ['{"type":"sale.updated","number":"S0000001"}']
