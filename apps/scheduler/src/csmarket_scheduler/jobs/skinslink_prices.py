"""Every 2 minutes: roll Skinslink's stock onto the catalogue and reprice
(``skins.prices.sync_skinslink_prices``) — independent of the Waxpeer price sync, so
Skinslink prices appear, and leave when the mirror goes stale, without a Waxpeer key.

The logic lives in ``skins.prices``; it does nothing while Skinslink is off and nothing of
an earlier roll-up is left. A failure is logged by type only.
"""

from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from csmarket.core.clock import now
from csmarket.core.config import get_settings
from csmarket.core.db import get_session_factory
from csmarket.core.logging import get_logger
from csmarket.core.redis import get_redis
from csmarket.modules.skins.prices import sync_skinslink_prices

from csmarket_scheduler.startup import first_run_after

log = get_logger("csmarket.scheduler.skinslink_prices")

JOB_ID = "skinslink.prices"
INTERVAL_SECONDS = 120


async def run() -> None:
    """One tick. Never raises."""
    try:
        await sync_skinslink_prices(
            get_session_factory(), get_redis(), settings=get_settings(), at=now()
        )
    except Exception as exc:  # noqa: BLE001 -- a tick never raises; the next one retries
        log.warning("skinslink.prices.failed", error=type(exc).__name__)


def register(scheduler: AsyncIOScheduler) -> None:
    """Every :data:`INTERVAL_SECONDS`; first run 105 s after start."""
    scheduler.add_job(
        run,
        trigger="interval",
        seconds=INTERVAL_SECONDS,
        id=JOB_ID,
        next_run_time=first_run_after(105),
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )
    log.info("scheduler.job.registered", job=JOB_ID, interval_seconds=INTERVAL_SECONDS)
