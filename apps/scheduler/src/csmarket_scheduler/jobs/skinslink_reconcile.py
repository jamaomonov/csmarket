"""Every 30 s: poll open Skinslink purchases and buy pending ones (``orders.skinslink_reconcile``).

The fallback when a webhook is lost (spec 2026-10-06 §6); the logic lives in ``orders``.
Skipped without an API key; runs with the switch off too, so open orders still settle.
``max_instances=1`` and ``coalesce=True``. A failure is
logged by type only.
"""

from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from csmarket.core.config import get_settings
from csmarket.core.db import get_session_factory
from csmarket.core.logging import get_logger
from csmarket.modules.orders.api import reconcile_skinslink
from csmarket.modules.skins.api import trade_client
from csmarket.modules.skinslink.api import client_for

from csmarket_scheduler.startup import first_run_after

log = get_logger("csmarket.scheduler.skinslink_reconcile")

JOB_ID = "skinslink.reconcile"
INTERVAL_SECONDS = 30


async def run() -> None:
    """One tick. Never raises."""
    settings = get_settings()
    # The key, not the switch: orders paid before the switch went off are followed to the end
    # (the tick only looks at open Skinslink orders).
    if not settings.skinslink_api_key:
        return
    try:
        looked = await reconcile_skinslink(
            get_session_factory(),
            client_for(settings, timeout_seconds=settings.skinslink_buy_timeout_seconds),
            settings=settings,
            waxpeer=trade_client(settings),
        )
    except Exception as exc:  # noqa: BLE001 -- a tick never raises; the next one retries
        log.warning("skinslink.reconcile.failed", error=type(exc).__name__)
        return
    if looked:
        log.info("skinslink.reconcile.tick", orders=looked)


def register(scheduler: AsyncIOScheduler) -> None:
    """Every :data:`INTERVAL_SECONDS`; first run 75 s after start."""
    scheduler.add_job(
        run,
        trigger="interval",
        seconds=INTERVAL_SECONDS,
        id=JOB_ID,
        next_run_time=first_run_after(75),
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )
    log.info("scheduler.job.registered", job=JOB_ID, interval_seconds=INTERVAL_SECONDS)
