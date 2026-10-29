"""Every 60 s: ask Skinslink about the owner's open desk deposits (``desk.poll_deposits``).

The fallback for statuses Skinslink sends no webhook for; the webhook only makes a deposit
due sooner. Skipped without a Skinslink key. ``max_instances=1`` and ``coalesce=True``. A
failure is logged by type only.
"""

from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from csmarket.core.config import get_settings
from csmarket.core.db import get_session_factory
from csmarket.core.logging import get_logger
from csmarket.modules.desk.api import poll_deposits
from csmarket.modules.skinslink.api import deposit_client_for

from csmarket_scheduler.startup import first_run_after

log = get_logger("csmarket.scheduler.desk_poll")

JOB_ID = "desk.poll"
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
        looked = await poll_deposits(get_session_factory(), client)
    except Exception as exc:  # noqa: BLE001 -- a tick never raises; the next one retries
        log.warning("desk.poll.failed", error=type(exc).__name__)
        return
    if looked:
        log.info("desk.poll.tick", deposits=looked)


def register(scheduler: AsyncIOScheduler) -> None:
    """Every :data:`INTERVAL_SECONDS`; first run 500 s after start."""
    scheduler.add_job(
        run,
        trigger="interval",
        seconds=INTERVAL_SECONDS,
        id=JOB_ID,
        next_run_time=first_run_after(500),
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )
    log.info("scheduler.job.registered", job=JOB_ID, interval_seconds=INTERVAL_SECONDS)
