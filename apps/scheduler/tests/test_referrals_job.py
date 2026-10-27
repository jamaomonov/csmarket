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
from prometheus_client import REGISTRY


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


async def test_a_failed_accrue_still_settles_and_sets_the_gauge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settle = AsyncMock(return_value=SettleResult())
    monkeypatch.setattr(referrals, "get_session_factory", lambda: _FakeSession)
    monkeypatch.setattr(referrals, "accrue", AsyncMock(side_effect=RuntimeError("db")))
    monkeypatch.setattr(referrals, "settle", settle)
    monkeypatch.setattr(referrals, "stuck_count", AsyncMock(return_value=4))
    await referrals.run()
    settle.assert_awaited_once()
    assert REGISTRY.get_sample_value("csmarket_referral_rewards_stuck") == 4


async def test_run_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    failing = AsyncMock(side_effect=RuntimeError("db"))
    monkeypatch.setattr(referrals, "get_session_factory", lambda: _FakeSession)
    for name in ("accrue", "settle", "stuck_count"):
        monkeypatch.setattr(referrals, name, failing)
    await referrals.run()


def test_registers_hourly() -> None:
    scheduler = AsyncIOScheduler(timezone="UTC")
    referrals.register(scheduler)
    (job,) = scheduler.get_jobs()
    assert job.id == "referrals.rewards"
    assert job.trigger.interval == timedelta(seconds=3600)
    delay = job.next_run_time - datetime.now(UTC)
    assert timedelta(0) < delay <= timedelta(seconds=480)
