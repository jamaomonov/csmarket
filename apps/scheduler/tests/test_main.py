"""The scheduler builds, starts and stops (Review Focus 5)."""

from __future__ import annotations

import asyncio
import signal

import pytest
from csmarket_scheduler import main
from csmarket_scheduler.main import build_scheduler, run


@pytest.fixture(autouse=True)
def _no_metrics_server(monkeypatch: pytest.MonkeyPatch) -> None:
    """``run()`` must not bind the real metrics port in every test."""
    monkeypatch.setattr(main, "start_metrics_server", lambda: True)


def test_build_scheduler_is_utc_with_the_registered_jobs() -> None:
    scheduler = build_scheduler()
    assert str(scheduler.timezone) == "UTC"
    assert [job.id for job in scheduler.get_jobs()] == [
        "auth.purge_refresh_tokens",
        "fx.refresh",
        "skins.catalog_import",
        "skins.price_sync",
        "skinslink.mirror",
        "skinslink.reconcile",
        "skinslink.balance",
        "sources.prices",
        "lisskins.snapshot",
        "wallet.topup_expiry",
        "click.timeout",
        "payme.timeout",
        "uzum.timeout",
        "orders.expiry",
        "trades.reconcile",
        "trades.protection",
        "trades.audit",
        "orders.health",
        "orders.erase_trade_links",
    ]


async def test_run_stops_on_signal() -> None:
    asyncio.get_running_loop().call_later(0.2, signal.raise_signal, signal.SIGTERM)
    await asyncio.wait_for(run(), timeout=5)


async def test_run_starts_the_metrics_server(monkeypatch: pytest.MonkeyPatch) -> None:
    started: list[bool] = []
    monkeypatch.setattr(main, "start_metrics_server", lambda: started.append(True) or True)
    asyncio.get_running_loop().call_later(0.2, signal.raise_signal, signal.SIGTERM)
    await asyncio.wait_for(run(), timeout=5)
    assert started == [True]
