"""Hourly USD/UZS refresh (ruling Q3): the CBU, else the fallback source once the newest rate is
``fx_fallback_after_hours`` old (``fx.service.refresh_with_fallback``). Every run exports the
newest rate's age for the FxRateStale / FxRateExpiring alerts, success or not."""

from __future__ import annotations

from datetime import timedelta
from functools import partial

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from csmarket.core.config import get_settings
from csmarket.core.db import get_session_factory
from csmarket.core.logging import get_logger
from csmarket.core.metrics import set_fx_rate_age
from csmarket.core.redis import get_redis
from csmarket.modules.fx.api import (
    CbuError,
    fetch_fallback_usd_uzs,
    fetch_usd_uzs,
    rate_age,
    refresh_with_fallback,
)

from csmarket_scheduler.startup import first_run_after

log = get_logger("csmarket.scheduler.fx_refresh")

JOB_ID = "fx.refresh"


async def _refresh_once() -> None:
    settings = get_settings()
    primary = partial(fetch_usd_uzs, url=settings.fx_cbu_url, timeout=settings.fx_timeout_seconds)
    fallback = partial(
        fetch_fallback_usd_uzs, url=settings.fx_fallback_url, timeout=settings.fx_timeout_seconds
    )
    async with get_session_factory()() as db:
        await refresh_with_fallback(
            db,
            get_redis(),
            primary=primary,
            fallback=fallback,
            fallback_after=timedelta(hours=settings.fx_fallback_after_hours),
        )


async def _export_age() -> None:
    try:
        async with get_session_factory()() as db:
            age = await rate_age(db)
    except Exception as exc:  # noqa: BLE001 -- a gauge must not fail the job
        log.warning("fx.age_unread", error=type(exc).__name__)
        return
    set_fx_rate_age(None if age is None else age.total_seconds())


async def run() -> bool:
    """One refresh; ``False`` (logged) on any failure — the last snapshot keeps serving."""
    ok = True
    try:
        await _refresh_once()
    except CbuError as exc:
        log.warning("fx.refresh.failed", error=type(exc).__name__, reason=str(exc))
        ok = False
    except Exception:
        log.exception("fx.refresh.crashed")
        ok = False
    await _export_age()
    return ok


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
