"""Scheduler entrypoint. Run as ``python -m csmarket_scheduler.main``."""

from __future__ import annotations

import asyncio
import signal

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from csmarket.core.config import get_settings
from csmarket.core.logging import configure_logging, get_logger
from csmarket.core.observability import init_sentry

# Imported for their side effect: ``RefreshToken`` relates to ``User``, so both mappers
# must be registered before any job opens a session (AGENTS.md §4).
from csmarket.modules.auth import models as _auth_models  # noqa: F401
from csmarket.modules.fx import models as _fx_models  # noqa: F401
from csmarket.modules.skins import models as _skins_models  # noqa: F401
from csmarket.modules.users import models as _users_models  # noqa: F401

from csmarket_scheduler.jobs import (
    fx_refresh,
    purge_refresh_tokens,
    skins_catalog_import,
    skins_price_sync,
)

configure_logging()
log = get_logger("csmarket.scheduler")


def build_scheduler() -> AsyncIOScheduler:
    """The AsyncIO scheduler with every production job attached.

    Keep the body short: each ``jobs/<name>.register(scheduler)`` owns its own
    trigger and first-run stagger.
    """
    scheduler = AsyncIOScheduler(timezone="UTC")
    purge_refresh_tokens.register(scheduler)
    fx_refresh.register(scheduler)
    skins_catalog_import.register(scheduler)
    skins_price_sync.register(scheduler)
    return scheduler


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
