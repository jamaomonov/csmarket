"""``skinslink.prices``: calls the Skinslink reprice every tick (it decides whether to work);
never raises; every 2 minutes."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from csmarket_scheduler.jobs import source_prices as job


async def test_a_tick_reprices(monkeypatch: pytest.MonkeyPatch) -> None:
    tick = AsyncMock(return_value=True)
    monkeypatch.setattr(job, "sync_source_prices", tick)
    await job.run()
    tick.assert_awaited_once()


async def test_a_failure_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(job, "sync_source_prices", AsyncMock(side_effect=RuntimeError("x")))
    await job.run()


def test_registers_every_2_minutes() -> None:
    scheduler = AsyncIOScheduler()
    job.register(scheduler)
    registered = scheduler.get_job(job.JOB_ID)
    assert registered is not None
    assert registered.trigger.interval.total_seconds() == 120
