"""``public_api.feed``: builds the snapshot every minute, never raises."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from csmarket_scheduler.jobs import public_feed as job


def _patch_db(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    session = MagicMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr(job, "get_session_factory", lambda: lambda: session)
    monkeypatch.setattr(job, "get_redis", lambda: "redis")
    return session


async def test_a_tick_builds_the_snapshot(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _patch_db(monkeypatch)
    build = AsyncMock(return_value=3)
    monkeypatch.setattr(job, "build_snapshot", build)
    await job.run()
    build.assert_awaited_once()
    assert build.await_args is not None
    assert build.await_args.args == (session, "redis")


async def test_a_failure_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_db(monkeypatch)
    monkeypatch.setattr(job, "build_snapshot", AsyncMock(side_effect=RuntimeError("x")))
    await job.run()


def test_registers_every_minute() -> None:
    scheduler = AsyncIOScheduler()
    job.register(scheduler)
    registered = scheduler.get_job(job.JOB_ID)
    assert registered is not None
    assert registered.trigger.interval.total_seconds() == 60
