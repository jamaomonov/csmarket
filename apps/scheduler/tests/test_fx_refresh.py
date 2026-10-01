"""``fx.refresh``: the wrapper never raises; registration is hourly with a 20 s first run."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from csmarket.modules.fx.cbu import CbuError
from csmarket_scheduler.jobs import fx_refresh


async def test_run_never_raises_on_cbu_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fx_refresh, "_refresh_once", AsyncMock(side_effect=CbuError("down")))
    assert await fx_refresh.run() is False


async def test_run_never_raises_on_a_crash(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fx_refresh, "_refresh_once", AsyncMock(side_effect=RuntimeError("boom")))
    assert await fx_refresh.run() is False


async def test_run_reports_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fx_refresh, "_refresh_once", AsyncMock(return_value=None))
    assert await fx_refresh.run() is True


def test_registers_on_the_configured_interval_with_an_early_first_run() -> None:
    scheduler = AsyncIOScheduler(timezone="UTC")
    fx_refresh.register(scheduler)
    (job,) = scheduler.get_jobs()
    assert job.id == "fx.refresh"
    assert job.trigger.interval == timedelta(minutes=60)
    assert job.next_run_time - datetime.now(UTC) <= timedelta(seconds=20)
