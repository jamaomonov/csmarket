"""``sales.poll``: runs while a Skinslink key is set, never raises, every 60 s."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from csmarket.core.config import get_settings
from csmarket_scheduler.jobs import sales_poll as job


def _settings(monkeypatch: pytest.MonkeyPatch, **update: object) -> None:
    s = get_settings().model_copy(update=update)
    monkeypatch.setattr(job, "get_settings", lambda: s)


async def test_skipped_without_a_key(monkeypatch: pytest.MonkeyPatch) -> None:
    tick = AsyncMock()
    monkeypatch.setattr(job, "poll_sales", tick)
    _settings(monkeypatch, skinslink_api_key="")
    await job.run()
    tick.assert_not_awaited()


async def test_switched_off_with_a_key_still_settles_open_sales(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tick = AsyncMock(return_value=0)
    monkeypatch.setattr(job, "poll_sales", tick)
    _settings(monkeypatch, sales_enabled=False, skinslink_api_key="k")
    await job.run()
    tick.assert_awaited_once()


async def test_a_failure_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(job, "poll_sales", AsyncMock(side_effect=RuntimeError("boom")))
    _settings(monkeypatch, skinslink_api_key="k")
    await job.run()


def test_registers_every_60_seconds() -> None:
    scheduler = AsyncIOScheduler()
    job.register(scheduler)
    registered = scheduler.get_job(job.JOB_ID)
    assert registered is not None
    assert registered.trigger.interval.total_seconds() == 60
