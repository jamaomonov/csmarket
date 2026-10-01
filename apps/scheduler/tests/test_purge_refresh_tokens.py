"""``auth.purge_refresh_tokens``: registration and the one-sweep wrapper."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import TracebackType
from typing import Self

import pytest
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from csmarket_scheduler.jobs import purge_refresh_tokens


def test_registers_daily_with_an_early_first_run() -> None:
    scheduler = AsyncIOScheduler(timezone="UTC")
    purge_refresh_tokens.register(scheduler)
    (job,) = scheduler.get_jobs()
    assert job.id == "auth.purge_refresh_tokens"
    assert job.trigger.interval == timedelta(hours=24)
    assert job.next_run_time - datetime.now(UTC) <= timedelta(minutes=5)


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


async def test_run_purges_one_batch_and_commits(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _FakeSession()

    async def fake_purge(db: _FakeSession) -> int:
        assert db is session
        assert not session.committed
        return 7

    monkeypatch.setattr(purge_refresh_tokens, "get_session_factory", lambda: lambda: session)
    monkeypatch.setattr(purge_refresh_tokens, "purge_stale_refresh_tokens", fake_purge)

    assert await purge_refresh_tokens.run() == 7
    assert session.committed
