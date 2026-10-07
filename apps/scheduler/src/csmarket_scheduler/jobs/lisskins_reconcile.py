# apps/scheduler/src/csmarket_scheduler/jobs/lisskins_reconcile.py
"""Every 30 s: buy pending LIS-SKINS orders and poll the rest in one ``market/info`` call
(``orders.lisskins_reconcile``; spec 2026-10-07 §6 — there is no webhook).

Skipped without an API key; runs with the switch off too, so open orders still settle.
``max_instances=1`` and ``coalesce=True``. A failure is logged by type only.
"""

from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from csmarket.core.config import get_settings
from csmarket.core.db import get_session_factory
from csmarket.core.logging import get_logger
from csmarket.modules.lisskins.api import client_for
from csmarket.modules.orders.api import reconcile_lisskins
from csmarket.modules.skins.api import trade_client

from csmarket_scheduler.startup import first_run_after

log = get_logger("csmarket.scheduler.lisskins_reconcile")

JOB_ID = "lisskins.reconcile"
INTERVAL_SECONDS = 30


async def run() -> None:
    """One tick. Never raises."""
    settings = get_settings()
    # The key, not the switch: orders paid before a switch-off are followed to the end.
    if not settings.lisskins_api_key:
        return
    try:
        looked = await reconcile_lisskins(
            get_session_factory(),
            client_for(settings, timeout_seconds=settings.lisskins_buy_timeout_seconds),
            settings=settings,
            waxpeer=trade_client(settings),
        )
    except Exception as exc:  # noqa: BLE001 -- a tick never raises; the next one retries
        log.warning("lisskins.reconcile.failed", error=type(exc).__name__)
        return
    if looked:
        log.info("lisskins.reconcile.tick", orders=looked)


def register(scheduler: AsyncIOScheduler) -> None:
    """Every :data:`INTERVAL_SECONDS`; first run 340 s after start."""
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
