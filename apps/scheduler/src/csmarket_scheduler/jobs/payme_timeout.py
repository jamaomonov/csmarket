"""Every 5 minutes: cancel Payme transactions Payme created but never performed or cancelled.

A buyer who opened Payme's checkout and walked away leaves a state-1 transaction and a
pending attempt; after 12 hours (``payme.TIMEOUT``) the transaction goes to state −1 with
reason 4 and the attempt is cancelled, so the top-up expiry sweep can close the top-up.
The logic is ``payme.cancel_stale``; one bounded batch per tick. A failure is logged and
the next tick retries.
"""

from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from csmarket.core.db import get_session_factory
from csmarket.core.logging import get_logger
from csmarket.modules.payme.api import cancel_stale

from csmarket_scheduler.startup import first_run_after

log = get_logger("csmarket.scheduler.payme_timeout")

JOB_ID = "payme.timeout"


async def _cancel_once() -> int:
    async with get_session_factory()() as db:
        count = await cancel_stale(db)
        await db.commit()
    return count


async def run() -> int | None:
    """One sweep; ``None`` (logged) on any failure — never raises.

    Returns:
        How many Payme transactions were cancelled, or ``None`` when the sweep failed.
    """
    try:
        count = await _cancel_once()
    except Exception:
        log.exception("payme.timeout.crashed")
        return None
    log.info("payme.timeout.done", count=count)
    return count


def register(scheduler: AsyncIOScheduler) -> None:
    """Every 5 minutes; first run 180 s after start (staggered from the other jobs)."""
    scheduler.add_job(
        run,
        trigger="interval",
        minutes=5,
        id=JOB_ID,
        next_run_time=first_run_after(180),
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )
