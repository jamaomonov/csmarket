"""``skinslink.mirror``: gated by ``skinslink_active``, stamps a good tick, never raises."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from csmarket.core.config import get_settings
from csmarket.modules.skinslink.api import SkinslinkUnavailableError
from csmarket.modules.skinslink.mirror import MirrorResult
from csmarket_scheduler.jobs import skinslink_mirror as job

ACTIVE = {"skinslink_enabled": True, "skinslink_api_key": "k", "skinslink_secret": "s"}


def _settings(monkeypatch: pytest.MonkeyPatch, *, active: bool) -> None:
    s = get_settings().model_copy(update=ACTIVE if active else {})
    monkeypatch.setattr(job, "get_settings", lambda: s)


async def test_skipped_while_inactive(monkeypatch: pytest.MonkeyPatch) -> None:
    sync = AsyncMock()
    monkeypatch.setattr(job, "sync_mirror", sync)
    _settings(monkeypatch, active=False)
    await job.run()
    sync.assert_not_awaited()


async def test_a_good_tick_stamps_the_gauge(monkeypatch: pytest.MonkeyPatch) -> None:
    _settings(monkeypatch, active=True)
    monkeypatch.setattr(
        job,
        "sync_mirror",
        AsyncMock(return_value=MirrorResult(mode="events", upserts=1, removes=0, pages=1)),
    )
    stamp = MagicMock()
    monkeypatch.setattr(job, "set_skinslink_mirror_synced", stamp)
    await job.run()
    stamp.assert_called_once()


async def test_a_failure_never_raises_and_stamps_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    _settings(monkeypatch, active=True)
    monkeypatch.setattr(job, "sync_mirror", AsyncMock(side_effect=SkinslinkUnavailableError("x")))
    stamp = MagicMock()
    monkeypatch.setattr(job, "set_skinslink_mirror_synced", stamp)
    await job.run()
    stamp.assert_not_called()
    monkeypatch.setattr(job, "sync_mirror", AsyncMock(side_effect=RuntimeError("boom")))
    await job.run()


def test_registers_every_15_seconds() -> None:
    scheduler = AsyncIOScheduler()
    job.register(scheduler)
    registered = scheduler.get_job(job.JOB_ID)
    assert registered is not None
    assert registered.trigger.interval.total_seconds() == 15
