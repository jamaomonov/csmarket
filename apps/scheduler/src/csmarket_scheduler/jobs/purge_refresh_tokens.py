"""Daily: delete refresh tokens that expired or were revoked over 7 days ago."""

from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from csmarket.core.db import get_session_factory
from csmarket.core.logging import get_logger
from csmarket.modules.auth.service import purge_stale_refresh_tokens

from csmarket_scheduler.startup import first_run_after

log = get_logger("csmarket.scheduler.purge_refresh_tokens")
JOB_ID = "auth.purge_refresh_tokens"


async def run() -> int:
    """One sweep (bounded batch); the next day's sweep continues a backlog.

    Returns:
        How many rows were deleted.
    """
    async with get_session_factory()() as db:
        deleted = await purge_stale_refresh_tokens(db)
        await db.commit()
    log.info("auth.refresh_tokens_purged", deleted=deleted)
    return deleted


def register(scheduler: AsyncIOScheduler) -> None:
    """Daily, first run five minutes after boot so restarts can't starve it."""
    scheduler.add_job(
        run,
        "interval",
        hours=24,
        id=JOB_ID,
        next_run_time=first_run_after(300),
        max_instances=1,
        coalesce=True,
    )
