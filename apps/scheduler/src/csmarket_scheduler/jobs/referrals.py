"""Every hour: write rewards for newly delivered orders of referred buyers, then credit the
ones whose 8-day hold is over (``referrals.rewards.accrue`` / ``settle``; this job only times
them). A failure is logged and the next tick retries; both steps are idempotent."""

from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from csmarket.core.db import get_session_factory
from csmarket.core.logging import get_logger
from csmarket.modules.referrals.rewards import accrue, settle

from csmarket_scheduler.startup import first_run_after

log = get_logger("csmarket.scheduler.referrals")

JOB_ID = "referrals.rewards"


async def run() -> None:
    """Accrue, then settle; a failure is logged, not raised."""
    try:
        async with get_session_factory()() as db:
            await accrue(db)
            result = await settle(db)
        log.info(
            "scheduler.referrals.settled",
            credited=result.credited,
            cancelled=result.cancelled,
            waiting=result.waiting,
        )
    except Exception:
        log.exception("scheduler.referrals.crashed")


def register(scheduler: AsyncIOScheduler) -> None:
    """Every 3600 s; first run 480 s after start (≥ 15 s from the other jobs' first runs)."""
    scheduler.add_job(
        run,
        trigger="interval",
        seconds=3600,
        id=JOB_ID,
        next_run_time=first_run_after(480),
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )
