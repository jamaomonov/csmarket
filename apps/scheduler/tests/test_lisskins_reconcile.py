"""``lisskins.reconcile``: runs with a key even when switched off, never raises, every 30 s."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from csmarket.core.config import get_settings
from csmarket_scheduler.jobs import lisskins_reconcile as job


def _settings(monkeypatch: pytest.MonkeyPatch, **update: object) -> None:
    s = get_settings().model_copy(update=update)
    monkeypatch.setattr(job, "get_settings", lambda: s)


async def test_without_a_key_nothing_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    tick = AsyncMock()
    monkeypatch.setattr(job, "reconcile_lisskins", tick)
    _settings(monkeypatch, lisskins_api_key="")
    await job.run()
    tick.assert_not_awaited()


async def test_a_key_is_enough_to_settle_open_orders(monkeypatch: pytest.MonkeyPatch) -> None:
    tick = AsyncMock(return_value=0)
    monkeypatch.setattr(job, "reconcile_lisskins", tick)
    _settings(monkeypatch, lisskins_api_key="k", lisskins_enabled=False)
    await job.run()
    tick.assert_awaited_once()


async def test_a_failure_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(job, "reconcile_lisskins", AsyncMock(side_effect=RuntimeError("boom")))
    _settings(monkeypatch, lisskins_api_key="k")
    await job.run()


def test_registers_every_30_seconds() -> None:
    scheduler = AsyncIOScheduler()
    job.register(scheduler)
    registered = scheduler.get_job(job.JOB_ID)
    assert registered is not None
    assert registered.trigger.interval.total_seconds() == 30
