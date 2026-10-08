"""Every 5 minutes: read the Skinslink balance (``skinslink.balance``) and say whether
Skinslink is on (``csmarket_skinslink_enabled`` gates the Skinslink alerts).

The logic lives in ``skinslink.balance``; this only times it. A failure is logged by type.
"""

from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from csmarket.core.config import get_settings
from csmarket.core.logging import get_logger
from csmarket.core.metrics import set_skinslink_enabled
from csmarket.core.redis import get_redis
from csmarket.modules.skinslink.api import client_for, refresh_balance

from csmarket_scheduler.startup import first_run_after

log = get_logger("csmarket.scheduler.skinslink_balance")

JOB_ID = "skinslink.balance"
INTERVAL_SECONDS = 300


async def run() -> None:
    """One tick. Never raises."""
    settings = get_settings()
    set_skinslink_enabled(enabled=settings.skinslink_active)
    if not settings.skinslink_active:
        return
    try:
        await refresh_balance(get_redis(), client_for(settings), settings=settings)
    except Exception as exc:  # noqa: BLE001 -- a tick never raises; the next one retries
        log.warning("skinslink.balance.tick_failed", error=type(exc).__name__)


def register(scheduler: AsyncIOScheduler) -> None:
    """Every :data:`INTERVAL_SECONDS`; first run 340 s after start (not urgent; swapped with lisskins.reconcile)."""
    scheduler.add_job(
        run,
        trigger="interval",
        seconds=INTERVAL_SECONDS,
        id=JOB_ID,
        next_run_time=first_run_after(340),
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )
    log.info("scheduler.job.registered", job=JOB_ID, interval_seconds=INTERVAL_SECONDS)
