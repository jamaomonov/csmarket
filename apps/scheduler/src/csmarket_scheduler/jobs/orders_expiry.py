"""Every minute: cancel unpaid orders past ``expires_at`` that no kassa holds.

The logic is ``orders.sweeps.expire_pending``; one bounded batch per tick, the next tick
continues a backlog. A failure is logged and the next tick retries.
"""

from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from csmarket.core.db import get_session_factory
from csmarket.core.logging import get_logger
from csmarket.modules.orders.sweeps import expire_pending

from csmarket_scheduler.startup import first_run_after

log = get_logger("csmarket.scheduler.orders_expiry")

JOB_ID = "orders.expiry"


async def _expire_once() -> int:
    async with get_session_factory()() as db:
        count = await expire_pending(db)
        await db.commit()
    return count


async def run() -> int | None:
    """One sweep; ``None`` (logged) on any failure — never raises.

    Returns:
        How many orders were cancelled, or ``None`` when the sweep failed.
    """
    try:
        count = await _expire_once()
    except Exception:
        log.exception("orders.expiry.crashed")
        return None
    if count:
        log.info("orders.expiry.done", count=count)
    return count


def register(scheduler: AsyncIOScheduler) -> None:
    """Every 60 s; first run 220 s after start (staggered from the other jobs)."""
    scheduler.add_job(
        run,
        trigger="interval",
        seconds=60,
        id=JOB_ID,
        next_run_time=first_run_after(220),
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )
