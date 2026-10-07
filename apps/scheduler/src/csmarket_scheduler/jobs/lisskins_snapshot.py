"""Every 5 minutes: snapshot LIS-SKINS' instant lots (``skins.source_prices.sync_lisskins``).

Skipped unless ``lisskins_active``. ``max_instances=1`` and ``coalesce=True``: a slow
download (~855 MB) is never joined by the next tick. A failure is logged by type only and
the last snapshot stays; ``LisskinsSnapshotStale`` notices when it ages.
"""

from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from csmarket.core.config import get_settings
from csmarket.core.db import get_session_factory
from csmarket.core.logging import get_logger
from csmarket.core.metrics import set_lisskins_snapshot
from csmarket.core.redis import get_redis
from csmarket.modules.skins.source_prices import sync_lisskins

from csmarket_scheduler.startup import first_run_after

log = get_logger("csmarket.scheduler.lisskins_snapshot")

JOB_ID = "lisskins.snapshot"
INTERVAL_SECONDS = 300


async def run() -> None:
    """One tick. Never raises."""
    settings = get_settings()
    if not settings.lisskins_active:
        return
    try:
        result = await sync_lisskins(get_session_factory(), get_redis(), settings=settings)
    except Exception as exc:  # noqa: BLE001 -- a tick never raises; the next one retries
        log.warning("lisskins.snapshot.failed", error=type(exc).__name__)
        return
    if not result.refused and result.snapshot_at is not None:
        set_lisskins_snapshot(result.snapshot_at.timestamp())


def register(scheduler: AsyncIOScheduler) -> None:
    """Every :data:`INTERVAL_SECONDS`; first run 320 s after start."""
    scheduler.add_job(
        run,
        trigger="interval",
        seconds=INTERVAL_SECONDS,
        id=JOB_ID,
        next_run_time=first_run_after(320),
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )
    log.info("scheduler.job.registered", job=JOB_ID, interval_seconds=INTERVAL_SECONDS)
