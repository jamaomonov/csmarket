"""``wallet.topup_expiry``: the wrapper never raises; every 5 min, first run after 140 s."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import TracebackType
from typing import Self
from unittest.mock import AsyncMock

import pytest
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from csmarket_scheduler.jobs import topup_expiry


class _FakeSession:
    def __init__(self) -> None:
        self.committed = False

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        return None

    async def commit(self) -> None:
        self.committed = True


async def test_run_expires_one_batch_and_commits(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _FakeSession()

    async def fake_expire(db: _FakeSession) -> int:
        assert db is session
        assert not session.committed
        return 3

    monkeypatch.setattr(topup_expiry, "get_session_factory", lambda: lambda: session)
    monkeypatch.setattr(topup_expiry, "expire_stale", fake_expire)
    assert await topup_expiry.run() == 3
    assert session.committed


async def test_run_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(topup_expiry, "_expire_once", AsyncMock(side_effect=RuntimeError("db")))
    assert await topup_expiry.run() is None


def test_registers_every_five_minutes_first_run_after_140_s() -> None:
    scheduler = AsyncIOScheduler(timezone="UTC")
    topup_expiry.register(scheduler)
    (job,) = scheduler.get_jobs()
    assert job.id == "wallet.topup_expiry"
    assert job.trigger.interval == timedelta(minutes=5)
    delay = job.next_run_time - datetime.now(UTC)
    assert timedelta(seconds=130) < delay <= timedelta(seconds=140)
