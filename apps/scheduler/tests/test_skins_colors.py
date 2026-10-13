"""``skins.colors``: gated by the sync flag, never raises, every 5 minutes."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from csmarket_scheduler.jobs import skins_colors as job


async def test_skipped_while_sync_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    work = AsyncMock()
    monkeypatch.setattr(job, "refresh_colors", work)
    monkeypatch.setattr(job, "_sync_enabled", lambda: False)
    await job.run()
    work.assert_not_awaited()


async def test_runs_and_swallows_a_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(job, "_sync_enabled", lambda: True)
    monkeypatch.setattr(job, "get_session_factory", lambda: None)
    work = AsyncMock(side_effect=RuntimeError("cdn"))
    monkeypatch.setattr(job, "refresh_colors", work)
    await job.run()  # does not raise
    work.assert_awaited_once()


def test_registers_every_five_minutes_after_seven() -> None:
    scheduler = AsyncIOScheduler(timezone="UTC")
    job.register(scheduler)
    (registered,) = scheduler.get_jobs()
    assert registered.id == "skins.colors"
    assert registered.trigger.interval == timedelta(minutes=5)
    delta = registered.next_run_time - datetime.now(UTC)
    assert timedelta(seconds=400) <= delta <= timedelta(seconds=420)
