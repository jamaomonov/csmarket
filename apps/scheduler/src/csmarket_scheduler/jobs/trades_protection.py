"""Hourly: follow delivered trades through Steam's 7-day protection (ruling R5).

The logic is ``orders.sweeps.watch_protected``: a rollback after delivery opens the
attention ``rolled_back`` (money spent, R3). A no-op without a Waxpeer key (or the dev fake).
"""

from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from csmarket.core.config import get_settings
from csmarket.core.db import get_session_factory
from csmarket.core.logging import get_logger
from csmarket.modules.orders.sweeps import watch_protected
from csmarket.modules.skins.api import trade_client

from csmarket_scheduler.startup import first_run_after

log = get_logger("csmarket.scheduler.trades_protection")

JOB_ID = "trades.protection"


async def run() -> int | None:
    """One watch; ``None`` when skipped or on any failure (logged) — never raises.

    Returns:
        How many trades were in protection, or ``None``.
    """
    try:
        settings = get_settings()
        if not (settings.waxpeer_api_key or settings.waxpeer_fake):  # nothing to ask
            return None
        async with get_session_factory()() as db:
            return await watch_protected(db, trade_client(settings))
    except Exception:
        log.exception("trades.protection.crashed")
        return None


def register(scheduler: AsyncIOScheduler) -> None:
    """Hourly; first run 280 s after start (a restart must not push it an hour out)."""
    scheduler.add_job(
        run,
        trigger="interval",
        hours=1,
        id=JOB_ID,
        next_run_time=first_run_after(280),
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )
