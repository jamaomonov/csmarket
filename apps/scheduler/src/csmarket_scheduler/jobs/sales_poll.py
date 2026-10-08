"""Every 60 s: ask Skinslink about open sales (``sales.reconcile.poll_sales``).

The fallback for the statuses Skinslink sends no webhook for (spec 2026-10-08 §6); the logic
lives in ``sales``. Skipped without a Skinslink key; runs with selling switched off too, so
open sales still settle. ``max_instances=1`` and ``coalesce=True``. A failure is logged by
type only.
"""

from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from csmarket.core.config import get_settings
from csmarket.core.db import get_session_factory
from csmarket.core.logging import get_logger
from csmarket.modules.sales.api import poll_sales
from csmarket.modules.skinslink.api import deposit_client_for

from csmarket_scheduler.startup import first_run_after

log = get_logger("csmarket.scheduler.sales_poll")

JOB_ID = "sales.poll"
INTERVAL_SECONDS = 60


async def run() -> None:
    """One tick. Never raises."""
    settings = get_settings()
    if not settings.skinslink_api_key:
        return
    client = deposit_client_for(
        settings, timeout_seconds=settings.skinslink_request_timeout_seconds
    )
    try:
        looked = await poll_sales(get_session_factory(), client)
    except Exception as exc:  # noqa: BLE001 -- a tick never raises; the next one retries
        log.warning("sales.poll.failed", error=type(exc).__name__)
        return
    if looked:
        log.info("sales.poll.tick", sales=looked)


def register(scheduler: AsyncIOScheduler) -> None:
    """Every :data:`INTERVAL_SECONDS`; first run 380 s after start."""
    scheduler.add_job(
        run,
        trigger="interval",
        seconds=INTERVAL_SECONDS,
        id=JOB_ID,
        next_run_time=first_run_after(380),
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )
    log.info("scheduler.job.registered", job=JOB_ID, interval_seconds=INTERVAL_SECONDS)
