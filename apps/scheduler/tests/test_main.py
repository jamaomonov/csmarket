"""The scheduler builds, starts and stops with zero jobs (Review Focus 5)."""

from __future__ import annotations

import asyncio
import signal

from csmarket_scheduler.main import build_scheduler, run


def test_build_scheduler_is_utc_and_empty_in_m0() -> None:
    scheduler = build_scheduler()
    assert str(scheduler.timezone) == "UTC"
    assert scheduler.get_jobs() == []


async def test_run_stops_on_signal_with_no_jobs() -> None:
    asyncio.get_running_loop().call_later(0.2, signal.raise_signal, signal.SIGTERM)
    await asyncio.wait_for(run(), timeout=5)
