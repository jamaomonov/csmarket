"""``orders.health``: gauges set from one reading, the balance on every 5th tick only."""

from __future__ import annotations

import socket
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import TracebackType
from typing import Self
from unittest.mock import AsyncMock

import pytest
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from csmarket.core.config import Settings, get_settings
from csmarket.modules.orders.health import Health
from csmarket_scheduler import metrics
from csmarket_scheduler.jobs import orders_health
from prometheus_client import REGISTRY


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


def _gauge(name: str, **labels: str) -> float | None:
    return REGISTRY.get_sample_value(name, labels)


@pytest.fixture(autouse=True)
def _fresh_ticks(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(orders_health, "_ticks", 0)
    monkeypatch.setattr(orders_health, "get_session_factory", lambda: _Session)
    settings: Settings = get_settings().model_copy(
        update={"waxpeer_api_key": "test-key-not-real", "waxpeer_balance_alert_usd": Decimal("50")}
    )
    monkeypatch.setattr(orders_health, "get_settings", lambda: settings)
    monkeypatch.setattr(orders_health, "trade_client", lambda _settings: object())


def _health(balance: Decimal | None = None) -> Health:
    return Health(
        paid_stuck=2,
        buying_stuck=1,
        trade_sent_unpolled=3,
        attention=4,
        waxpeer_balance_usd=balance,
    )


async def test_a_tick_sets_every_gauge(monkeypatch: pytest.MonkeyPatch) -> None:
    measure = AsyncMock(return_value=_health(Decimal("42.5")))
    monkeypatch.setattr(orders_health, "measure", measure)
    assert await orders_health.run() == _health(Decimal("42.5"))
    assert _gauge("csmarket_orders_stuck", state="paid") == 2
    assert _gauge("csmarket_orders_stuck", state="buying") == 1
    assert _gauge("csmarket_orders_stuck", state="trade_sent_unpolled") == 3
    assert _gauge("csmarket_trades_attention") == 4
    assert _gauge("csmarket_waxpeer_balance_usd") == 42.5
    assert _gauge("csmarket_waxpeer_balance_threshold_usd") == 50.0


async def test_the_balance_is_asked_for_on_every_fifth_tick_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clients: list[object | None] = []

    async def fake_measure(db: object, client: object | None, *, settings: Settings) -> Health:
        clients.append(client)
        return _health()

    monkeypatch.setattr(orders_health, "measure", fake_measure)
    for _ in range(11):
        await orders_health.run()
    asked = [i for i, client in enumerate(clients) if client is not None]
    assert asked == [0, 5, 10]


async def test_no_waxpeer_key_means_no_balance_call(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings().model_copy(update={"waxpeer_api_key": "", "waxpeer_fake": False})
    monkeypatch.setattr(orders_health, "get_settings", lambda: settings)
    seen: list[object | None] = []

    async def fake_measure(db: object, client: object | None, *, settings: Settings) -> Health:
        seen.append(client)
        return _health()

    monkeypatch.setattr(orders_health, "measure", fake_measure)
    await orders_health.run()
    assert seen == [None]


async def test_an_unreadable_balance_keeps_the_last_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(orders_health, "measure", AsyncMock(return_value=_health(Decimal(77))))
    await orders_health.run()
    monkeypatch.setattr(orders_health, "measure", AsyncMock(return_value=_health(None)))
    await orders_health.run()
    assert _gauge("csmarket_waxpeer_balance_usd") == 77.0
    assert _gauge("csmarket_waxpeer_balance_threshold_usd") == 50.0


async def test_the_job_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(orders_health, "measure", AsyncMock(side_effect=RuntimeError("db")))
    assert await orders_health.run() is None


def test_every_minute_first_run_after_260_s() -> None:
    scheduler = AsyncIOScheduler(timezone="UTC")
    orders_health.register(scheduler)
    (job,) = scheduler.get_jobs()
    assert job.id == "orders.health"
    assert job.trigger.interval == timedelta(seconds=60)
    delay: timedelta = job.next_run_time - datetime.now(UTC)
    assert timedelta(seconds=250) < delay <= timedelta(seconds=260)
    assert (job.coalesce, job.max_instances) == (True, 1)


def test_the_scheduler_serves_on_its_own_port(monkeypatch: pytest.MonkeyPatch) -> None:
    with socket.socket() as taken:
        taken.bind(("0.0.0.0", 0))
        taken.listen()
        port = taken.getsockname()[1]
        settings = get_settings().model_copy(update={"scheduler_metrics_port": port})
        monkeypatch.setattr(metrics, "get_settings", lambda: settings)
        assert metrics.start_metrics_server() is False  # taken: logged, not raised
