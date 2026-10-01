"""The orders and trade jobs: triggers, first runs, the Waxpeer gate, and never raising."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import TracebackType
from typing import Any, Self
from unittest.mock import AsyncMock

import pytest
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from csmarket.core.config import Settings, get_settings
from csmarket_scheduler.jobs import (
    orders_expiry,
    trades_audit,
    trades_protection,
    trades_reconcile,
)


class _FakeSession:
    def __init__(self) -> None:
        self.committed = False

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        return None

    async def commit(self) -> None:
        self.committed = True


def _only_job(register: Any) -> Any:
    scheduler = AsyncIOScheduler(timezone="UTC")
    register(scheduler)
    (job,) = scheduler.get_jobs()
    return job


def _first_run_in(job: Any) -> timedelta:
    delay: timedelta = job.next_run_time - datetime.now(UTC)
    return delay


def _settings(monkeypatch: pytest.MonkeyPatch, module: Any, **update: Any) -> None:
    settings: Settings = get_settings().model_copy(update=update)
    monkeypatch.setattr(module, "get_settings", lambda: settings)


# --- orders.expiry -------------------------------------------------------------------------


async def test_expiry_cancels_one_batch_and_commits(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _FakeSession()

    async def fake_expire(db: _FakeSession) -> int:
        assert db is session
        return 2

    monkeypatch.setattr(orders_expiry, "get_session_factory", lambda: lambda: session)
    monkeypatch.setattr(orders_expiry, "expire_pending", fake_expire)
    assert await orders_expiry.run() == 2
    assert session.committed


async def test_expiry_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(orders_expiry, "_expire_once", AsyncMock(side_effect=RuntimeError("db")))
    assert await orders_expiry.run() is None


def test_expiry_every_minute_first_run_after_220_s() -> None:
    job = _only_job(orders_expiry.register)
    assert job.id == "orders.expiry"
    assert job.trigger.interval == timedelta(seconds=60)
    assert timedelta(seconds=210) < _first_run_in(job) <= timedelta(seconds=220)
    assert (job.coalesce, job.max_instances) == (True, 1)


# --- trades.reconcile ----------------------------------------------------------------------


async def test_reconcile_is_a_no_op_without_waxpeer(monkeypatch: pytest.MonkeyPatch) -> None:
    _settings(monkeypatch, trades_reconcile, waxpeer_api_key="", waxpeer_fake=False)
    sweep = AsyncMock(return_value=1)
    monkeypatch.setattr(trades_reconcile, "reconcile", sweep)
    assert await trades_reconcile.run() is None
    sweep.assert_not_awaited()


@pytest.mark.parametrize(
    "update",
    [{"waxpeer_api_key": "test-key-not-real"}, {"waxpeer_api_key": "", "waxpeer_fake": True}],
)
async def test_reconcile_runs_with_a_key_or_the_fake(
    monkeypatch: pytest.MonkeyPatch, update: dict[str, Any]
) -> None:
    _settings(monkeypatch, trades_reconcile, **update)
    client, factory = object(), object()
    seen: dict[str, Any] = {}

    async def sweep(db_factory: object, got: object, *, settings: Settings) -> int:
        seen.update(factory=db_factory, client=got, settings=settings)
        return 3

    monkeypatch.setattr(trades_reconcile, "reconcile", sweep)
    monkeypatch.setattr(trades_reconcile, "trade_client", lambda _settings: client)
    monkeypatch.setattr(trades_reconcile, "get_session_factory", lambda: factory)
    assert await trades_reconcile.run() == 3
    assert (seen["factory"], seen["client"]) == (factory, client)


async def test_reconcile_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _settings(monkeypatch, trades_reconcile, waxpeer_api_key="test-key-not-real")
    monkeypatch.setattr(trades_reconcile, "reconcile", AsyncMock(side_effect=RuntimeError("x")))
    monkeypatch.setattr(trades_reconcile, "trade_client", lambda _settings: object())
    monkeypatch.setattr(trades_reconcile, "get_session_factory", object)
    assert await trades_reconcile.run() is None


def test_reconcile_every_trades_reconcile_seconds_first_run_after_240_s(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _settings(monkeypatch, trades_reconcile, trades_reconcile_seconds=10)
    job = _only_job(trades_reconcile.register)
    assert job.id == "trades.reconcile"
    assert job.trigger.interval == timedelta(seconds=10)
    assert timedelta(seconds=230) < _first_run_in(job) <= timedelta(seconds=240)
    assert (job.coalesce, job.max_instances) == (True, 1)


# --- trades.protection and trades.audit ----------------------------------------------------


@pytest.mark.parametrize(
    ("module", "sweep_name"),
    [(trades_protection, "watch_protected"), (trades_audit, "audit_recent")],
)
async def test_watch_and_audit_run_on_one_session(
    monkeypatch: pytest.MonkeyPatch, module: Any, sweep_name: str
) -> None:
    _settings(monkeypatch, module, waxpeer_api_key="test-key-not-real")
    session, client = _FakeSession(), object()

    async def sweep(db: _FakeSession, got: object) -> int:
        assert (db, got) == (session, client)
        return 4

    monkeypatch.setattr(module, sweep_name, sweep)
    monkeypatch.setattr(module, "trade_client", lambda _settings: client)
    monkeypatch.setattr(module, "get_session_factory", lambda: lambda: session)
    assert await module.run() == 4


@pytest.mark.parametrize(
    ("module", "sweep_name"),
    [(trades_protection, "watch_protected"), (trades_audit, "audit_recent")],
)
async def test_watch_and_audit_skip_without_waxpeer(
    monkeypatch: pytest.MonkeyPatch, module: Any, sweep_name: str
) -> None:
    _settings(monkeypatch, module, waxpeer_api_key="", waxpeer_fake=False)
    sweep = AsyncMock(return_value=1)
    monkeypatch.setattr(module, sweep_name, sweep)
    assert await module.run() is None
    sweep.assert_not_awaited()


@pytest.mark.parametrize(
    ("module", "sweep_name"),
    [(trades_protection, "watch_protected"), (trades_audit, "audit_recent")],
)
async def test_watch_and_audit_never_raise(
    monkeypatch: pytest.MonkeyPatch, module: Any, sweep_name: str
) -> None:
    _settings(monkeypatch, module, waxpeer_api_key="test-key-not-real")
    monkeypatch.setattr(module, sweep_name, AsyncMock(side_effect=RuntimeError("boom")))
    monkeypatch.setattr(module, "trade_client", lambda _settings: object())
    monkeypatch.setattr(module, "get_session_factory", lambda: _FakeSession)
    assert await module.run() is None


def test_protection_hourly_first_run_after_280_s() -> None:
    job = _only_job(trades_protection.register)
    assert job.id == "trades.protection"
    assert job.trigger.interval == timedelta(hours=1)
    assert timedelta(seconds=270) < _first_run_in(job) <= timedelta(seconds=280)
    assert (job.coalesce, job.max_instances) == (True, 1)


def test_audit_daily_at_23_30_utc_coalesced() -> None:
    job = _only_job(trades_audit.register)
    assert job.id == "trades.audit"
    assert isinstance(job.trigger, CronTrigger)
    fields = {f.name: str(f) for f in job.trigger.fields}
    assert (fields["hour"], fields["minute"]) == ("23", "30")
    assert str(job.trigger.timezone) == "UTC"
    assert (job.coalesce, job.max_instances) == (True, 1)
    nxt = job.trigger.get_next_fire_time(None, datetime(2026, 10, 2, 12, 0, tzinfo=UTC))
    assert nxt == datetime(2026, 10, 2, 23, 30, tzinfo=UTC)
