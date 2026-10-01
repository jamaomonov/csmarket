"""Five-minute fold of Waxpeer's CSV snapshot onto ``skin_items``.

Streams the snapshot per tick and writes only rows whose prices moved (the logic lives in
``skins.prices``). Skipped while ``skins_sync_enabled`` is off or the Waxpeer key is empty.
``max_instances=1`` and ``coalesce=True``: a slow tick must never be joined by the next one.
The outcome lands in Redis (``skins.job_status``) for the admin status card.
"""

from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from csmarket.core.config import get_settings
from csmarket.core.db import get_session_factory
from csmarket.core.logging import get_logger
from csmarket.core.redis import get_redis
from csmarket.modules.skins.job_status import JOB_PRICE_SYNC, record_job
from csmarket.modules.skins.prices import sync_prices
from csmarket.modules.skins.waxpeer import WaxpeerClient, WaxpeerError, WaxpeerUnavailableError

from csmarket_scheduler.startup import first_run_after

log = get_logger("csmarket.scheduler.skins_price_sync")

JOB_ID = "skins.price_sync"


def _settings_ok() -> bool:
    settings = get_settings()
    return settings.skins_sync_enabled and bool(settings.waxpeer_api_key)


async def run() -> None:
    """One tick. A Waxpeer failure is recorded and the previous prices stand. Never raises."""
    if not _settings_ok():
        log.info("skins.prices.skipped", reason="sync disabled or no waxpeer key")
        return
    settings = get_settings()
    client = WaxpeerClient(
        api_key=settings.waxpeer_api_key,
        base_url=settings.waxpeer_base_url,
        timeout_seconds=settings.waxpeer_request_timeout_seconds,
    )
    try:
        result = await sync_prices(get_session_factory(), client, get_redis())
    except (WaxpeerError, WaxpeerUnavailableError) as exc:
        # The class name only: Waxpeer's text can echo the request, key included.
        log.warning("skins.prices.failed", error=type(exc).__name__)
        await record_job(
            get_redis(), JOB_PRICE_SYNC, ok=False, counters={}, error=type(exc).__name__
        )
        return
    except Exception as exc:
        log.exception("skins.prices.crashed")
        await record_job(
            get_redis(), JOB_PRICE_SYNC, ok=False, counters={}, error=type(exc).__name__
        )
        return
    counters = {"changed": result.changed, "deactivated": result.deactivated, "stubs": result.stubs}
    if result.refused:
        await record_job(
            get_redis(), JOB_PRICE_SYNC, ok=False, counters=counters, error="thin_snapshot"
        )
        return
    await record_job(get_redis(), JOB_PRICE_SYNC, ok=True, counters=counters, error=None)


def register(scheduler: AsyncIOScheduler) -> None:
    """Every ``skins_snapshot_interval_minutes``; first run 60 s after start."""
    minutes = max(1, int(get_settings().skins_snapshot_interval_minutes))
    scheduler.add_job(
        run,
        trigger="interval",
        minutes=minutes,
        id=JOB_ID,
        next_run_time=first_run_after(60),
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )
    log.info("scheduler.job.registered", job=JOB_ID, interval_minutes=minutes)
