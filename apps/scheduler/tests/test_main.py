"""The scheduler builds, starts and stops (Review Focus 5)."""

from __future__ import annotations

import asyncio
import signal

from csmarket_scheduler.main import build_scheduler, run


def test_build_scheduler_is_utc_with_the_m1_jobs() -> None:
    scheduler = build_scheduler()
    assert str(scheduler.timezone) == "UTC"
    assert [job.id for job in scheduler.get_jobs()] == ["auth.purge_refresh_tokens"]


async def test_run_stops_on_signal() -> None:
    asyncio.get_running_loop().call_later(0.2, signal.raise_signal, signal.SIGTERM)
    await asyncio.wait_for(run(), timeout=5)
