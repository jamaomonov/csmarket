"""Every 5 minutes: expire top-ups no kassa took up (ruling R8).

The logic is ``payments.expire_stale``; one bounded batch per tick, the next tick continues
a backlog. A failure is logged and the next tick retries.
"""

from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from csmarket.core.db import get_session_factory
from csmarket.core.logging import get_logger
from csmarket.modules.payments.api import expire_stale

from csmarket_scheduler.startup import first_run_after

log = get_logger("csmarket.scheduler.topup_expiry")

JOB_ID = "wallet.topup_expiry"


async def _expire_once() -> int:
    async with get_session_factory()() as db:
        count = await expire_stale(db)
        await db.commit()
    return count


async def run() -> int | None:
    """One sweep; ``None`` (logged) on any failure — never raises.

    Returns:
        How many top-ups expired, or ``None`` when the sweep failed.
    """
    try:
        count = await _expire_once()
    except Exception:
        log.exception("wallet.topup_expiry.crashed")
        return None
    log.info("wallet.topup_expiry.done", count=count)
    return count


def register(scheduler: AsyncIOScheduler) -> None:
    """Every 5 minutes; first run 140 s after start (staggered from the other jobs)."""
    scheduler.add_job(
        run,
        trigger="interval",
        minutes=5,
        id=JOB_ID,
        next_run_time=first_run_after(140),
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )
