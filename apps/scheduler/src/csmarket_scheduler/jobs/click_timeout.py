"""Every 5 minutes: cancel Click transactions Click prepared but never completed.

A buyer who opened ``my.click.uz`` and walked away leaves a ``PREPARED`` row and a pending
attempt; after 30 minutes (``click.PREPARE_TIMEOUT``) the row goes ``CANCELLED`` and the
attempt is cancelled, so the top-up expiry sweep can close the top-up. The logic is
``click.cancel_stale``; one bounded batch per tick. A failure is logged and the next tick
retries.
"""

from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from csmarket.core.db import get_session_factory
from csmarket.core.logging import get_logger
from csmarket.modules.click.api import cancel_stale

from csmarket_scheduler.startup import first_run_after

log = get_logger("csmarket.scheduler.click_timeout")

JOB_ID = "click.timeout"


async def _cancel_once() -> int:
    async with get_session_factory()() as db:
        count = await cancel_stale(db)
        await db.commit()
    return count


async def run() -> int | None:
    """One sweep; ``None`` (logged) on any failure — never raises.

    Returns:
        How many Click transactions were cancelled, or ``None`` when the sweep failed.
    """
    try:
        count = await _cancel_once()
    except Exception:
        log.exception("click.timeout.crashed")
        return None
    log.info("click.timeout.done", count=count)
    return count


def register(scheduler: AsyncIOScheduler) -> None:
    """Every 5 minutes; first run 160 s after start (staggered from the other jobs)."""
    scheduler.add_job(
        run,
        trigger="interval",
        minutes=5,
        id=JOB_ID,
        next_run_time=first_run_after(160),
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )
