"""``payment_holds``: the gauge follows the open holds; a failure is logged, never raised."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import TracebackType
from typing import Self
from unittest.mock import AsyncMock

import pytest
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from csmarket_scheduler.jobs import payment_holds
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


def _gauge(reason: str) -> float | None:
    return REGISTRY.get_sample_value("csmarket_payment_holds_open", {"reason": reason})


async def test_run_sets_the_gauge_per_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(payment_holds, "get_session_factory", lambda: _FakeSession)
    monkeypatch.setattr(
        payment_holds,
        "open_counts",
        AsyncMock(return_value={"kassa_limit": 2, "user_limit": 0, "check_failed": 1}),
    )
    await payment_holds.run()
    assert _gauge("kassa_limit") == 2
    assert _gauge("user_limit") == 0
    assert _gauge("check_failed") == 1


async def test_run_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(payment_holds, "get_session_factory", lambda: _FakeSession)
    monkeypatch.setattr(payment_holds, "open_counts", AsyncMock(side_effect=RuntimeError("db")))
    await payment_holds.run()


def test_registers_every_minute() -> None:
    scheduler = AsyncIOScheduler(timezone="UTC")
    payment_holds.register(scheduler)
    (job,) = scheduler.get_jobs()
    assert job.id == "payment_holds"
    assert job.trigger.interval == timedelta(seconds=60)
    delay = job.next_run_time - datetime.now(UTC)
    assert timedelta(0) < delay <= timedelta(seconds=5)
