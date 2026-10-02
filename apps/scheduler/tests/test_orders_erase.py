"""The nightly erase job: both erasers on one session, cron 22:00 UTC, never raises."""

from __future__ import annotations

from datetime import UTC, datetime
from types import TracebackType
from typing import Self
from unittest.mock import AsyncMock

import pytest
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from csmarket_scheduler.jobs import orders_erase


class _Session:
    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        return None


async def test_a_run_erases_links_and_addresses(monkeypatch: pytest.MonkeyPatch) -> None:
    links, addresses = AsyncMock(return_value=3), AsyncMock(return_value=2)
    monkeypatch.setattr(orders_erase, "erase_old_trade_links", links)
    monkeypatch.setattr(orders_erase, "erase_old_verify_addresses", addresses)
    monkeypatch.setattr(orders_erase, "get_session_factory", lambda: _Session)
    assert await orders_erase.run() == (3, 2)
    assert links.await_args is not None
    assert addresses.await_args is not None
    assert links.await_args.kwargs["at"].tzinfo is not None


async def test_the_job_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(orders_erase, "erase_old_trade_links", AsyncMock(side_effect=RuntimeError))
    monkeypatch.setattr(orders_erase, "get_session_factory", lambda: _Session)
    assert await orders_erase.run() is None


def test_nightly_at_22_utc_coalesced() -> None:
    scheduler = AsyncIOScheduler(timezone="UTC")
    orders_erase.register(scheduler)
    (job,) = scheduler.get_jobs()
    assert job.id == "orders.erase_trade_links"
    assert isinstance(job.trigger, CronTrigger)
    fields = {f.name: str(f) for f in job.trigger.fields}
    assert (fields["hour"], fields["minute"]) == ("22", "0")
    assert (job.coalesce, job.max_instances) == (True, 1)
    nxt = job.trigger.get_next_fire_time(None, datetime(2026, 10, 2, 12, 0, tzinfo=UTC))
    assert nxt == datetime(2026, 10, 2, 22, 0, tzinfo=UTC)
