"""``p2p.sweep``: one tick commits and reports; the wrapper never raises; every 30 s."""

from __future__ import annotations

from datetime import UTC, datetime
from types import TracebackType
from typing import Self
from unittest.mock import AsyncMock

import pytest
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from csmarket.modules.p2p.reservations import SweepResult
from csmarket_scheduler.jobs import p2p_sweep


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


async def test_run_sweeps_commits_and_reports(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _FakeSession()
    last = datetime(2026, 10, 19, 10, 0, tzinfo=UTC)
    reported: list[tuple[int, float | None]] = []

    async def fake_tick(db: _FakeSession, *, at: datetime) -> tuple[SweepResult, datetime]:
        assert db is session
        return SweepResult(expired=2, released=1), last

    monkeypatch.setattr(p2p_sweep, "get_session_factory", lambda: lambda: session)
    monkeypatch.setattr(p2p_sweep, "sweep_tick", fake_tick)
    monkeypatch.setattr(p2p_sweep, "record_p2p_sweep", lambda e, t: reported.append((e, t)))
    assert await p2p_sweep.run() == (2, 1)
    assert session.committed
    assert reported == [(2, last.timestamp())]


async def test_run_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(p2p_sweep, "_sweep_once", AsyncMock(side_effect=RuntimeError("db")))
    assert await p2p_sweep.run() is None


def test_register_runs_every_thirty_seconds() -> None:
    scheduler = AsyncIOScheduler(timezone="UTC")
    p2p_sweep.register(scheduler)
    job = scheduler.get_job(p2p_sweep.JOB_ID)
    assert job is not None
    assert job.trigger.interval.total_seconds() == 30
