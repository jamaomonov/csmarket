"""Every minute: export the unresolved bad reviews as a gauge (no alert; the admin menu
counts them). The count is ``reviews.bad_open_count``; this job only times it. A failure is
logged and the next tick retries."""

from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from csmarket.core.db import get_session_factory
from csmarket.core.logging import get_logger
from csmarket.core.metrics import set_reviews_bad_open
from csmarket.modules.reviews.api import bad_open_count

from csmarket_scheduler.startup import first_run_after

log = get_logger("csmarket.scheduler.reviews")

JOB_ID = "reviews.bad_open"


async def run() -> None:
    """Count and set the gauge; a failure is logged, not raised."""
    try:
        async with get_session_factory()() as db:
            count = await bad_open_count(db)
        set_reviews_bad_open(count)
    except Exception:
        log.exception("scheduler.reviews.crashed")


def register(scheduler: AsyncIOScheduler) -> None:
    """Every 60 s; first run 460 s after start (≥ 15 s from the other jobs' first runs)."""
    scheduler.add_job(
        run,
        trigger="interval",
        seconds=60,
        id=JOB_ID,
        next_run_time=first_run_after(460),
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )
