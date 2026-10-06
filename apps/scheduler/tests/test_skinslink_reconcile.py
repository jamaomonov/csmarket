"""``skinslink.reconcile``: gated by ``skinslink_active``, never raises, every 30 s."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from csmarket.core.config import get_settings
from csmarket_scheduler.jobs import skinslink_reconcile as job

ACTIVE = {"skinslink_enabled": True, "skinslink_api_key": "k", "skinslink_secret": "s"}


def _settings(monkeypatch: pytest.MonkeyPatch, *, active: bool) -> None:
    s = get_settings().model_copy(update=ACTIVE if active else {})
    monkeypatch.setattr(job, "get_settings", lambda: s)


async def test_skipped_without_a_key(monkeypatch: pytest.MonkeyPatch) -> None:
    tick = AsyncMock()
    monkeypatch.setattr(job, "reconcile_skinslink", tick)
    _settings(monkeypatch, active=False)
    await job.run()
    tick.assert_not_awaited()


async def test_switched_off_with_a_key_still_settles_open_orders(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Orders paid before the switch went off are still followed to the end."""
    tick = AsyncMock(return_value=0)
    monkeypatch.setattr(job, "reconcile_skinslink", tick)
    s = get_settings().model_copy(update={"skinslink_enabled": False, "skinslink_api_key": "k"})
    monkeypatch.setattr(job, "get_settings", lambda: s)
    await job.run()
    tick.assert_awaited_once()


async def test_a_tick_runs_while_active(monkeypatch: pytest.MonkeyPatch) -> None:
    tick = AsyncMock(return_value=0)
    monkeypatch.setattr(job, "reconcile_skinslink", tick)
    _settings(monkeypatch, active=True)
    await job.run()
    tick.assert_awaited_once()


async def test_a_failure_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(job, "reconcile_skinslink", AsyncMock(side_effect=RuntimeError("boom")))
    _settings(monkeypatch, active=True)
    await job.run()


def test_registers_every_30_seconds() -> None:
    scheduler = AsyncIOScheduler()
    job.register(scheduler)
    registered = scheduler.get_job(job.JOB_ID)
    assert registered is not None
    assert registered.trigger.interval.total_seconds() == 30
