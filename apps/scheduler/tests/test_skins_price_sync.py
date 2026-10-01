"""``skins.price_sync``: gated by flag and key, records its outcome, never raises."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from csmarket.modules.skins.prices import ApplyResult
from csmarket.modules.skins.waxpeer import WaxpeerRateLimitedError
from csmarket_scheduler.jobs import skins_price_sync as job


def _enable(monkeypatch: pytest.MonkeyPatch, *, sync: bool = True, key: str = "k") -> None:
    monkeypatch.setattr(job, "_settings_ok", lambda: sync and bool(key))


async def test_skipped_without_flag_or_key(monkeypatch: pytest.MonkeyPatch) -> None:
    sync = AsyncMock()
    monkeypatch.setattr(job, "sync_prices", sync)
    _enable(monkeypatch, key="")
    await job.run()
    sync.assert_not_awaited()


async def test_skipped_while_sync_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    sync = AsyncMock()
    monkeypatch.setattr(job, "sync_prices", sync)
    _enable(monkeypatch, sync=False)
    await job.run()
    sync.assert_not_awaited()


async def test_records_a_good_tick(monkeypatch: pytest.MonkeyPatch) -> None:
    rec = AsyncMock()
    _enable(monkeypatch)
    monkeypatch.setattr(
        job,
        "sync_prices",
        AsyncMock(return_value=ApplyResult(changed=5, deactivated=1, stubs=0)),
    )
    monkeypatch.setattr(job, "record_job", rec)
    await job.run()
    assert rec.await_args is not None
    assert rec.await_args.kwargs["ok"] is True
    assert rec.await_args.kwargs["counters"] == {"changed": 5, "deactivated": 1, "stubs": 0}


async def test_a_refused_tick_is_not_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    rec = AsyncMock()
    _enable(monkeypatch)
    monkeypatch.setattr(
        job, "sync_prices", AsyncMock(return_value=ApplyResult(0, 0, 0, refused=True))
    )
    monkeypatch.setattr(job, "record_job", rec)
    await job.run()
    assert rec.await_args is not None
    assert rec.await_args.kwargs["ok"] is False
    assert rec.await_args.kwargs["error"] == "thin_snapshot"


async def test_waxpeer_trouble_is_recorded_not_raised(monkeypatch: pytest.MonkeyPatch) -> None:
    rec = AsyncMock()
    _enable(monkeypatch)
    monkeypatch.setattr(
        job,
        "sync_prices",
        AsyncMock(side_effect=WaxpeerRateLimitedError("429", retry_after_seconds=None)),
    )
    monkeypatch.setattr(job, "record_job", rec)
    await job.run()
    assert rec.await_args is not None
    assert rec.await_args.kwargs == {
        "ok": False,
        "counters": {},
        "error": "WaxpeerRateLimitedError",
    }


async def test_an_unexpected_crash_is_recorded_not_raised(monkeypatch: pytest.MonkeyPatch) -> None:
    rec = AsyncMock()
    _enable(monkeypatch)
    monkeypatch.setattr(job, "sync_prices", AsyncMock(side_effect=RuntimeError("secret text")))
    monkeypatch.setattr(job, "record_job", rec)
    await job.run()
    assert rec.await_args is not None
    assert rec.await_args.kwargs["error"] == "RuntimeError"


def test_registers_every_snapshot_interval_with_a_one_minute_first_run() -> None:
    scheduler = AsyncIOScheduler(timezone="UTC")
    job.register(scheduler)
    (registered,) = scheduler.get_jobs()
    assert registered.id == "skins.price_sync"
    assert registered.trigger.interval == timedelta(minutes=5)
    delta = registered.next_run_time - datetime.now(UTC)
    assert timedelta(seconds=40) <= delta <= timedelta(seconds=60)
