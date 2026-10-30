"""``desk.poll``: runs while a Skinslink key is set, never raises, every 60 s."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from csmarket.core.config import get_settings
from csmarket_scheduler.jobs import desk_poll as job


def _settings(monkeypatch: pytest.MonkeyPatch, **update: object) -> None:
    s = get_settings().model_copy(update=update)
    monkeypatch.setattr(job, "get_settings", lambda: s)


async def test_skipped_without_a_key(monkeypatch: pytest.MonkeyPatch) -> None:
    tick = AsyncMock()
    monkeypatch.setattr(job, "poll_deposits", tick)
    _settings(monkeypatch, skinslink_api_key="")
    await job.run()
    tick.assert_not_awaited()


async def test_a_failure_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(job, "poll_deposits", AsyncMock(side_effect=RuntimeError("boom")))
    _settings(monkeypatch, skinslink_api_key="k")
    await job.run()


def test_registers_every_60_seconds() -> None:
    scheduler = AsyncIOScheduler()
    job.register(scheduler)
    registered = scheduler.get_job(job.JOB_ID)
    assert registered is not None
    assert registered.trigger.interval.total_seconds() == 60


async def test_the_bot_profile_is_read_only_with_a_steam_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tick = AsyncMock(return_value=0)
    monkeypatch.setattr(job, "poll_deposits", tick)
    _settings(monkeypatch, skinslink_api_key="k", steam_api_key="")
    await job.run()
    assert tick.await_args is not None
    assert tick.await_args.kwargs["persona"] is None
    _settings(monkeypatch, skinslink_api_key="k", steam_api_key="s")
    await job.run()
    assert tick.await_args.kwargs["persona"] is not None
