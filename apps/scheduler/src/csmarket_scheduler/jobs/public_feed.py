"""Every minute: rebuild the public API's catalogue snapshot in Redis
(``public_api.feed.build_snapshot``). The job only times it; a failure is logged by type
only and the previous snapshot keeps serving until its TTL.
"""

from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from csmarket.core.clock import now
from csmarket.core.db import get_session_factory
from csmarket.core.logging import get_logger
from csmarket.core.redis import get_redis
from csmarket.modules.public_api.feed import build_snapshot

from csmarket_scheduler.startup import first_run_after

log = get_logger("csmarket.scheduler.public_feed")

JOB_ID = "public_api.feed"
INTERVAL_SECONDS = 60


async def run() -> None:
    """One tick. Never raises."""
    try:
        async with get_session_factory()() as db:
            count = await build_snapshot(db, get_redis(), at=now())
        log.info("public_api.feed.built", items=count)
    except Exception as exc:  # noqa: BLE001 -- a tick never raises; the next one retries
        log.warning("public_api.feed.failed", error=type(exc).__name__)


def register(scheduler: AsyncIOScheduler) -> None:
    """Every :data:`INTERVAL_SECONDS`; first run 15 s after start."""
    scheduler.add_job(
        run,
        trigger="interval",
        seconds=INTERVAL_SECONDS,
        id=JOB_ID,
        next_run_time=first_run_after(15),
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )
    log.info("scheduler.job.registered", job=JOB_ID, interval_seconds=INTERVAL_SECONDS)
