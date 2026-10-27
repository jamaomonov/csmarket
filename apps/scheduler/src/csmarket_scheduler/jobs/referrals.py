"""Every hour: write rewards for newly delivered orders of referred buyers, credit the ones whose
8-day hold is over, and export how many are stuck past it (``referrals.rewards.accrue`` /
``settle`` / ``stuck_count``; this job only times them). Each step fails alone: a failed accrue
does not stop the crediting. Every step is idempotent; the next tick retries."""

from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from csmarket.core.db import get_session_factory
from csmarket.core.logging import get_logger
from csmarket.core.metrics import set_referral_rewards_stuck
from csmarket.modules.referrals.rewards import accrue, settle, stuck_count

from csmarket_scheduler.startup import first_run_after

log = get_logger("csmarket.scheduler.referrals")

JOB_ID = "referrals.rewards"


async def _accrue() -> None:
    try:
        async with get_session_factory()() as db:
            await accrue(db)
    except Exception:
        log.exception("scheduler.referrals.accrue_crashed")


async def _settle() -> None:
    try:
        async with get_session_factory()() as db:
            result = await settle(db)
        log.info(
            "scheduler.referrals.settled",
            credited=result.credited,
            cancelled=result.cancelled,
            waiting=result.waiting,
        )
    except Exception:
        log.exception("scheduler.referrals.settle_crashed")


async def _gauge() -> None:
    try:
        async with get_session_factory()() as db:
            set_referral_rewards_stuck(await stuck_count(db))
    except Exception:
        log.exception("scheduler.referrals.gauge_crashed")


async def run() -> None:
    """Accrue, settle, then the stuck gauge; each failure is logged, never raised."""
    await _accrue()
    await _settle()
    await _gauge()


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
