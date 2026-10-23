"""``reviews.bad_open``: the gauge follows the unresolved bad reviews; a failure is logged."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import TracebackType
from typing import Self
from unittest.mock import AsyncMock

import pytest
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from csmarket_scheduler.jobs import reviews
from prometheus_client import REGISTRY


class _FakeSession:
    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        return None


async def test_run_sets_the_gauge(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(reviews, "get_session_factory", lambda: _FakeSession)
    monkeypatch.setattr(reviews, "bad_open_count", AsyncMock(return_value=3))
    await reviews.run()
    assert REGISTRY.get_sample_value("csmarket_reviews_bad_open") == 3


async def test_run_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(reviews, "get_session_factory", lambda: _FakeSession)
    monkeypatch.setattr(reviews, "bad_open_count", AsyncMock(side_effect=RuntimeError("db")))
    await reviews.run()


def test_registers_every_minute() -> None:
    scheduler = AsyncIOScheduler(timezone="UTC")
    reviews.register(scheduler)
    (job,) = scheduler.get_jobs()
    assert job.id == "reviews.bad_open"
    assert job.trigger.interval == timedelta(seconds=60)
    delay = job.next_run_time - datetime.now(UTC)
    assert timedelta(0) < delay <= timedelta(seconds=460)
