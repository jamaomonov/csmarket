"""Nightly at 22:00 UTC (03:00 Tashkent): erase what an ended order no longer needs.

``orders.erase``: an order's trade-link token 30 days after it ended (decision D3), and a
``verify`` letter's address a week after it was queued. A cron trigger fires at its time
whatever the restarts, so it needs no first-run stagger.
"""

from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from csmarket.core.clock import now
from csmarket.core.db import get_session_factory
from csmarket.core.logging import get_logger
from csmarket.modules.orders.api import erase_old_trade_links, erase_old_verify_addresses

log = get_logger("csmarket.scheduler.orders_erase")

JOB_ID = "orders.erase_trade_links"
#: A run the scheduler missed (it was down at 22:00) still runs within this window.
MISFIRE_GRACE_SECONDS = 3600


async def run() -> tuple[int, int] | None:
    """One erase; ``None`` (logged) on any failure — never raises.

    Returns:
        ``(orders erased, verify addresses dropped)``, or ``None``.
    """
    try:
        at = now()
        async with get_session_factory()() as db:
            links = await erase_old_trade_links(db, at=at)
            addresses = await erase_old_verify_addresses(db, at=at)
    except Exception:
        log.exception("orders.erase.crashed")
        return None
    return links, addresses


def register(scheduler: AsyncIOScheduler) -> None:
    """Every day at 22:00 UTC, coalesced."""
    scheduler.add_job(
        run,
        trigger="cron",
        hour=22,
        minute=0,
        id=JOB_ID,
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=MISFIRE_GRACE_SECONDS,
    )
