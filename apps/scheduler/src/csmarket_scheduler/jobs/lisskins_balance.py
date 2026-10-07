"""Every 5 minutes: read the LIS-SKINS balance (``lisskins.balance``) and say whether
LIS-SKINS is on (``csmarket_lisskins_enabled`` gates the LIS-SKINS alerts).

The logic lives in ``lisskins.balance``; this only times it. A failure is logged by type.
"""

from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from csmarket.core.config import get_settings
from csmarket.core.logging import get_logger
from csmarket.core.metrics import set_lisskins_enabled
from csmarket.core.redis import get_redis
from csmarket.modules.lisskins.api import client_for, refresh_balance

from csmarket_scheduler.startup import first_run_after

log = get_logger("csmarket.scheduler.lisskins_balance")

JOB_ID = "lisskins.balance"
INTERVAL_SECONDS = 300


async def run() -> None:
    """One tick. Never raises."""
    settings = get_settings()
    set_lisskins_enabled(enabled=settings.lisskins_active)
    if not settings.lisskins_active:
        return
    try:
        await refresh_balance(get_redis(), client_for(settings), settings=settings)
    except Exception as exc:  # noqa: BLE001 -- a tick never raises; the next one retries
        log.warning("lisskins.balance.tick_failed", error=type(exc).__name__)


def register(scheduler: AsyncIOScheduler) -> None:
    """Every :data:`INTERVAL_SECONDS`; first run 360 s after start."""
    scheduler.add_job(
        run,
        trigger="interval",
        seconds=INTERVAL_SECONDS,
        id=JOB_ID,
        next_run_time=first_run_after(360),
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )
    log.info("scheduler.job.registered", job=JOB_ID, interval_seconds=INTERVAL_SECONDS)
