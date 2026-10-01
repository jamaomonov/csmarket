"""``skins.catalog_import``: gated by the sync flag, records its outcome, never raises."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from csmarket.modules.skins.bymykel import ImportSummary
from csmarket_scheduler.jobs import skins_catalog_import as job


async def test_skipped_while_sync_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    imp = AsyncMock()
    monkeypatch.setattr(job, "import_catalog", imp)
    monkeypatch.setattr(job, "_sync_enabled", lambda: False)
    await job.run()
    imp.assert_not_awaited()


async def test_records_success(monkeypatch: pytest.MonkeyPatch) -> None:
    rec = AsyncMock()
    monkeypatch.setattr(job, "_sync_enabled", lambda: True)
    monkeypatch.setattr(
        job, "import_catalog", AsyncMock(return_value=ImportSummary(files=11, rows=10, changed=2))
    )
    monkeypatch.setattr(job, "record_job", rec)
    await job.run()
    assert rec.await_args is not None
    assert rec.await_args.kwargs == {
        "ok": True,
        "counters": {"files": 11, "rows": 10, "changed": 2},
        "error": None,
    }


async def test_records_failure_without_raising(monkeypatch: pytest.MonkeyPatch) -> None:
    rec = AsyncMock()
    monkeypatch.setattr(job, "_sync_enabled", lambda: True)
    monkeypatch.setattr(job, "import_catalog", AsyncMock(side_effect=RuntimeError("x")))
    monkeypatch.setattr(job, "record_job", rec)
    await job.run()
    assert rec.await_args is not None
    assert rec.await_args.kwargs["ok"] is False
    assert rec.await_args.kwargs["error"] == "RuntimeError"


def test_registers_daily_with_a_two_minute_first_run() -> None:
    scheduler = AsyncIOScheduler(timezone="UTC")
    job.register(scheduler)
    (registered,) = scheduler.get_jobs()
    assert registered.id == "skins.catalog_import"
    assert registered.trigger.interval == timedelta(hours=24)
    delta = registered.next_run_time - datetime.now(UTC)
    assert timedelta(seconds=100) <= delta <= timedelta(seconds=120)
