"""``referrals.rewards``: accrue then settle every hour; a failure is logged, not raised."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import TracebackType
from typing import Self
from unittest.mock import AsyncMock

import pytest
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from csmarket.modules.referrals.rewards import SettleResult
from csmarket_scheduler.jobs import referrals


class _FakeSession:
    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        return None


async def test_run_accrues_then_settles(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    async def accrue(_db: object) -> int:
        calls.append("accrue")
        return 1

    async def settle(_db: object) -> SettleResult:
        calls.append("settle")
        return SettleResult(credited=1)

    monkeypatch.setattr(referrals, "get_session_factory", lambda: _FakeSession)
    monkeypatch.setattr(referrals, "accrue", accrue)
    monkeypatch.setattr(referrals, "settle", settle)
    await referrals.run()
    assert calls == ["accrue", "settle"]


async def test_run_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(referrals, "get_session_factory", lambda: _FakeSession)
    monkeypatch.setattr(referrals, "accrue", AsyncMock(side_effect=RuntimeError("db")))
    await referrals.run()


def test_registers_hourly() -> None:
    scheduler = AsyncIOScheduler(timezone="UTC")
    referrals.register(scheduler)
    (job,) = scheduler.get_jobs()
    assert job.id == "referrals.rewards"
    assert job.trigger.interval == timedelta(seconds=3600)
    delay = job.next_run_time - datetime.now(UTC)
    assert timedelta(0) < delay <= timedelta(seconds=480)
