"""Every minute: export the open payment holds as a gauge (alert ``PaymentHeldForReview``).

The count is ``payments.open_counts``; this job only times it. A failure is logged and the
next tick retries.
"""

from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from csmarket.core.db import get_session_factory
from csmarket.core.logging import get_logger
from csmarket.core.metrics import set_payment_holds_open
from csmarket.modules.payments.api import open_counts

from csmarket_scheduler.startup import first_run_after

log = get_logger("csmarket.scheduler.payment_holds")

JOB_ID = "payment_holds"


async def run() -> None:
    """Count the open holds and set the gauge per reason; a failure is logged, not raised."""
    try:
        async with get_session_factory()() as db:
            counts = await open_counts(db)
        for reason, n in counts.items():
            set_payment_holds_open(reason, n)
    except Exception:
        log.exception("scheduler.payment_holds.crashed")


def register(scheduler: AsyncIOScheduler) -> None:
    """Every 60 s; first run 5 s after start (≥ 15 s from the other jobs' first runs)."""
    scheduler.add_job(
        run,
        trigger="interval",
        seconds=60,
        id=JOB_ID,
        next_run_time=first_run_after(5),
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )
