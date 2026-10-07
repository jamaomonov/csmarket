"""``lisskins.snapshot``: gated by ``lisskins_active``, stamps the export's time, never raises."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from csmarket.core.config import get_settings
from csmarket.modules.lisskins.api import SnapshotResult
from csmarket_scheduler.jobs import lisskins_snapshot as job
from prometheus_client import REGISTRY

AT = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)


def _settings(monkeypatch: pytest.MonkeyPatch, *, active: bool) -> None:
    update = {"lisskins_enabled": True, "lisskins_api_key": "k"} if active else {}
    s = get_settings().model_copy(update=update)
    monkeypatch.setattr(job, "get_settings", lambda: s)


async def test_inactive_does_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    sync = AsyncMock()
    monkeypatch.setattr(job, "sync_lisskins", sync)
    _settings(monkeypatch, active=False)
    await job.run()
    sync.assert_not_awaited()


async def test_a_good_tick_stamps_the_exports_time(monkeypatch: pytest.MonkeyPatch) -> None:
    result = SnapshotResult(refused=False, lots=3, items=1, snapshot_at=AT)
    monkeypatch.setattr(job, "sync_lisskins", AsyncMock(return_value=result))
    _settings(monkeypatch, active=True)
    await job.run()
    assert REGISTRY.get_sample_value("csmarket_lisskins_snapshot_timestamp_seconds") == (
        AT.timestamp()
    )


async def test_a_failure_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(job, "sync_lisskins", AsyncMock(side_effect=RuntimeError("boom")))
    _settings(monkeypatch, active=True)
    await job.run()


def test_registers_every_5_minutes() -> None:
    scheduler = AsyncIOScheduler()
    job.register(scheduler)
    registered = scheduler.get_job(job.JOB_ID)
    assert registered is not None
    assert registered.trigger.interval.total_seconds() == 300
