"""``lisskins.balance``: exports whether LIS-SKINS is on every tick; reads the balance only
while it is; never raises; every 5 minutes."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from csmarket.core.config import get_settings
from csmarket_scheduler.jobs import lisskins_balance as job
from prometheus_client import REGISTRY

ACTIVE = {"lisskins_enabled": True, "lisskins_api_key": "k"}


def _settings(monkeypatch: pytest.MonkeyPatch, *, active: bool) -> None:
    s = get_settings().model_copy(update=ACTIVE if active else {})
    monkeypatch.setattr(job, "get_settings", lambda: s)


async def test_inactive_exports_off_and_reads_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    read = AsyncMock()
    monkeypatch.setattr(job, "refresh_balance", read)
    _settings(monkeypatch, active=False)
    await job.run()
    read.assert_not_awaited()
    assert REGISTRY.get_sample_value("csmarket_lisskins_enabled") == 0


async def test_active_exports_on_and_reads(monkeypatch: pytest.MonkeyPatch) -> None:
    read = AsyncMock(return_value=None)
    monkeypatch.setattr(job, "refresh_balance", read)
    _settings(monkeypatch, active=True)
    await job.run()
    read.assert_awaited_once()
    assert REGISTRY.get_sample_value("csmarket_lisskins_enabled") == 1


async def test_a_failure_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(job, "refresh_balance", AsyncMock(side_effect=RuntimeError("boom")))
    _settings(monkeypatch, active=True)
    await job.run()


def test_registers_every_5_minutes() -> None:
    scheduler = AsyncIOScheduler()
    job.register(scheduler)
    registered = scheduler.get_job(job.JOB_ID)
    assert registered is not None
    assert registered.trigger.interval.total_seconds() == 300
