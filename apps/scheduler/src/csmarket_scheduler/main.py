"""Scheduler entrypoint. Run as ``python -m csmarket_scheduler.main``."""

from __future__ import annotations

import asyncio
import signal

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from csmarket.core.config import get_settings
from csmarket.core.logging import configure_logging, get_logger
from csmarket.core.observability import init_sentry

configure_logging()
log = get_logger("csmarket.scheduler")


def build_scheduler() -> AsyncIOScheduler:
    """The AsyncIO scheduler with every production job attached.

    Keep the body short: each ``jobs/<name>.register(scheduler)`` owns its own
    trigger and first-run stagger. No jobs in M0.
    """
    return AsyncIOScheduler(timezone="UTC")


async def run() -> None:
    """Start the scheduler and block until SIGINT/SIGTERM."""
    init_sentry(get_settings(), integrations="none")
    scheduler = build_scheduler()
    scheduler.start()
    log.info("scheduler.started", jobs=[job.id for job in scheduler.get_jobs()])

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    await stop.wait()

    # ``wait=False``: ``wait=True`` is a promise AsyncIOExecutor cannot keep (its own
    # source says so) and every job here is periodic and re-runnable — a deploy
    # landing mid-tick cuts the job and the next tick redoes it. The resulting
    # CancelledError is dropped by ``core.observability._before_send``.
    scheduler.shutdown(wait=False)
    log.info("scheduler.stopped")


if __name__ == "__main__":
    asyncio.run(run())
