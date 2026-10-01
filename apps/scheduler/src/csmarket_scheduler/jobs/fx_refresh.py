"""Hourly CBU USD/UZS refresh (ruling Q3). The logic is ``fx.service.refresh_usd_uzs``."""

from __future__ import annotations

from functools import partial

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from csmarket.core.config import get_settings
from csmarket.core.db import get_session_factory
from csmarket.core.logging import get_logger
from csmarket.core.redis import get_redis
from csmarket.modules.fx.api import CbuError, fetch_usd_uzs, refresh_usd_uzs

from csmarket_scheduler.startup import first_run_after

log = get_logger("csmarket.scheduler.fx_refresh")

JOB_ID = "fx.refresh"


async def _refresh_once() -> None:
    settings = get_settings()
    fetch = partial(fetch_usd_uzs, url=settings.fx_cbu_url, timeout=settings.fx_timeout_seconds)
    async with get_session_factory()() as db:
        await refresh_usd_uzs(db, get_redis(), fetch=fetch)


async def run() -> bool:
    """One refresh; ``False`` (logged) on any failure — the last snapshot keeps serving."""
    try:
        await _refresh_once()
    except CbuError as exc:
        log.warning("fx.refresh.failed", error=type(exc).__name__, reason=str(exc))
        return False
    except Exception:
        log.exception("fx.refresh.crashed")
        return False
    return True


def register(scheduler: AsyncIOScheduler) -> None:
    """Every ``fx_refresh_interval_minutes``; first run 20 s after start."""
    minutes = get_settings().fx_refresh_interval_minutes
    scheduler.add_job(
        run,
        trigger="interval",
        minutes=minutes,
        id=JOB_ID,
        next_run_time=first_run_after(20),
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )
