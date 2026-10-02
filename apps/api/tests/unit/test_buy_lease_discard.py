"""``orders.buy_lease.discard``: an attempt's exit never hangs on a stuck session (final
review minor 12)."""

from __future__ import annotations

import asyncio
from typing import Any, cast

import pytest
from csmarket.modules.orders import buy_lease
from sqlalchemy.ext.asyncio import AsyncSession


class _Session:
    """Stands in for an ``AsyncSession`` whose rollback / close may hang or fail."""

    def __init__(self, *, rollback: str = "ok", close: str = "ok") -> None:
        self._rollback, self._close = rollback, close
        self.calls: list[str] = []

    async def _act(self, name: str, how: str) -> None:
        self.calls.append(name)
        if how == "hang":
            await asyncio.sleep(3600)
        if how == "fail":
            raise ConnectionError(name)

    async def rollback(self) -> None:
        await self._act("rollback", self._rollback)

    async def close(self) -> None:
        await self._act("close", self._close)


def _db(session: _Session) -> AsyncSession:
    return cast(AsyncSession, session)  # a duck-typed stand-in: discard calls two methods


@pytest.fixture(autouse=True)
def _short(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(buy_lease, "_DISCARD_SECONDS", 0.05)


@pytest.mark.parametrize(
    ("rollback", "close", "calls"),
    [
        ("ok", "ok", ["rollback"]),
        ("fail", "ok", ["rollback", "close"]),
        ("hang", "ok", ["rollback", "close"]),
        ("hang", "hang", ["rollback", "close"]),
        ("fail", "fail", ["rollback", "close"]),
    ],
)
async def test_discard_is_bounded_and_never_raises(rollback: str, close: str, calls: Any) -> None:
    session = _Session(rollback=rollback, close=close)
    async with asyncio.timeout(1):  # well under an hour: both hangs were cut short
        await buy_lease.discard(_db(session))
    assert session.calls == calls
