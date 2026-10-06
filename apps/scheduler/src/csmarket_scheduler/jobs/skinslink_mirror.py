"""Every 15 s: keep the mirror of Skinslink's sale list current (``skinslink.mirror``).

The logic lives in ``skinslink.mirror``; this only times it. Skipped unless
``skinslink_active``. ``max_instances=1`` and ``coalesce=True``: a slow full load is never
joined by the next tick. A failure is logged by type only (Skinslink's text can echo the
request) and the mirror keeps its last good state; ``SkinslinkMirrorStale`` notices.
"""

from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from csmarket.core.clock import now
from csmarket.core.config import get_settings
from csmarket.core.db import get_session_factory
from csmarket.core.logging import get_logger
from csmarket.core.metrics import set_skinslink_mirror_synced
from csmarket.modules.skinslink.api import client_for
from csmarket.modules.skinslink.mirror import sync_mirror

from csmarket_scheduler.startup import first_run_after

log = get_logger("csmarket.scheduler.skinslink_mirror")

JOB_ID = "skinslink.mirror"
INTERVAL_SECONDS = 15


async def run() -> None:
    """One tick. Never raises."""
    settings = get_settings()
    if not settings.skinslink_active:
        return
    try:
        result = await sync_mirror(get_session_factory(), client_for(settings), now=now())
    except Exception as exc:  # noqa: BLE001 -- a tick never raises; the next one retries
        log.warning("skinslink.mirror.failed", error=type(exc).__name__)
        return
    set_skinslink_mirror_synced()
    if result.upserts or result.removes or result.mode != "events":
        log.info(
            "skinslink.mirror.synced",
            mode=result.mode,
            upserts=result.upserts,
            removes=result.removes,
            pages=result.pages,
        )


def register(scheduler: AsyncIOScheduler) -> None:
    """Every :data:`INTERVAL_SECONDS`; first run 45 s after start."""
    scheduler.add_job(
        run,
        trigger="interval",
        seconds=INTERVAL_SECONDS,
        id=JOB_ID,
        next_run_time=first_run_after(45),
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )
    log.info("scheduler.job.registered", job=JOB_ID, interval_seconds=INTERVAL_SECONDS)
