"""Daily import of the CS2 item catalogue from ByMykel/CSGO-API.

Metadata only — prices are ``skins_price_sync``'s. Skipped entirely while
``skins_sync_enabled`` is off, so a deploy with the flag down costs nothing.
``max_instances=1``: an import takes a minute or two and must not overlap itself.
The outcome lands in Redis (``skins.job_status``) for the admin status card.
"""

from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from csmarket.core.config import get_settings
from csmarket.core.db import get_session_factory
from csmarket.core.logging import get_logger
from csmarket.core.redis import get_redis
from csmarket.modules.skins.bymykel import import_catalog
from csmarket.modules.skins.job_status import JOB_IMPORT, record_job

from csmarket_scheduler.startup import first_run_after

log = get_logger("csmarket.scheduler.skins_catalog_import")

JOB_ID = "skins.catalog_import"


def _sync_enabled() -> bool:
    return get_settings().skins_sync_enabled


async def run() -> None:
    """One tick: fetch every file and upsert, or log that the flag is off. Never raises."""
    if not _sync_enabled():
        log.info("skins.import.skipped", reason="skins_sync_enabled=false")
        return
    try:
        summary = await import_catalog(
            get_session_factory(), base_url=get_settings().bymykel_base_url
        )
    except Exception as exc:
        log.exception("skins.import.failed")
        await record_job(get_redis(), JOB_IMPORT, ok=False, counters={}, error=type(exc).__name__)
        return
    counters = {"files": summary.files, "rows": summary.rows, "changed": summary.changed}
    log.info("skins.import.done", **counters)
    await record_job(get_redis(), JOB_IMPORT, ok=True, counters=counters, error=None)


def register(scheduler: AsyncIOScheduler) -> None:
    """Every ``skins_import_interval_hours``; first run 120 s after start."""
    hours = max(1, int(get_settings().skins_import_interval_hours))
    scheduler.add_job(
        run,
        trigger="interval",
        hours=hours,
        id=JOB_ID,
        next_run_time=first_run_after(120),
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )
    log.info("scheduler.job.registered", job=JOB_ID, interval_hours=hours)
