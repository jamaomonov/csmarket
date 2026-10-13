"""Every 5 minutes: read the colours of skin pictures not read yet (spec 2026-10-14-skin-colors).

Gated by ``skins_sync_enabled`` like the import (no catalogue, nothing to read). The work lives
in ``skins.color_job``; this only times it. ``max_instances=1``: a slow CDN tick must not
overlap the next.
"""

from __future__ import annotations

import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from csmarket.core.config import get_settings
from csmarket.core.db import get_session_factory
from csmarket.core.logging import get_logger
from csmarket.modules.skins.color_job import http_fetch, refresh_colors

from csmarket_scheduler.startup import first_run_after

log = get_logger("csmarket.scheduler.skins_colors")

JOB_ID = "skins.colors"


def _sync_enabled() -> bool:
    return get_settings().skins_sync_enabled


async def run() -> None:
    """One tick, or a log line that the flag is off. Never raises."""
    if not _sync_enabled():
        return
    try:
        async with httpx.AsyncClient(follow_redirects=True) as client:
            await refresh_colors(
                get_session_factory(),
                fetch=http_fetch(client),
                host=get_settings().skins_image_host,
            )
    except Exception:
        log.exception("skins.colors.failed")


def register(scheduler: AsyncIOScheduler) -> None:
    """Every 5 minutes; first run 420 s after start."""
    scheduler.add_job(
        run,
        trigger="interval",
        minutes=5,
        id=JOB_ID,
        next_run_time=first_run_after(420),
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )
    log.info("scheduler.job.registered", job=JOB_ID, interval_minutes=5)
