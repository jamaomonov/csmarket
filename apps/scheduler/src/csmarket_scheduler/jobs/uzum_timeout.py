"""Every 5 minutes: fail Uzum transactions Uzum created but never confirmed or reversed.

A buyer who opened Uzum's checkout and walked away leaves a ``CREATED`` transaction and a
pending attempt; after 30 minutes (``uzum.TIMEOUT``, Uzum's own spec) the transaction goes
``FAILED`` and the attempt is cancelled (unless another live Uzum row holds it), so the
top-up expiry sweep can close the top-up. The logic is ``uzum.fail_stale``; one bounded
batch per tick. A failure is logged and the next tick retries.
"""

from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from csmarket.core.db import get_session_factory
from csmarket.core.logging import get_logger
from csmarket.modules.uzum.api import fail_stale

from csmarket_scheduler.startup import first_run_after

log = get_logger("csmarket.scheduler.uzum_timeout")

JOB_ID = "uzum.timeout"


async def _fail_once() -> int:
    async with get_session_factory()() as db:
        count = await fail_stale(db)
        await db.commit()
    return count


async def run() -> int | None:
    """One sweep; ``None`` (logged) on any failure — never raises.

    Returns:
        How many Uzum transactions were failed, or ``None`` when the sweep failed.
    """
    try:
        count = await _fail_once()
    except Exception:
        log.exception("uzum.timeout.crashed")
        return None
    log.info("uzum.timeout.done", count=count)
    return count


def register(scheduler: AsyncIOScheduler) -> None:
    """Every 5 minutes; first run 200 s after start (staggered from the other jobs)."""
    scheduler.add_job(
        run,
        trigger="interval",
        minutes=5,
        id=JOB_ID,
        next_run_time=first_run_after(200),
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )
