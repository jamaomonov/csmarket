"""Daily at 23:30 UTC (04:30 Tashkent): read the last 14 days of settled trades again.

The logic is ``orders.sweeps.audit_recent``: each divergence from Waxpeer is recorded once
(``audit_verdict``) and opens the attention ``audit_divergence``. A cron trigger fires at
its time whatever the restarts, so it needs no first-run stagger. A no-op without a Waxpeer
key (or the dev fake).
"""

from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from csmarket.core.config import get_settings
from csmarket.core.db import get_session_factory
from csmarket.core.logging import get_logger
from csmarket.modules.orders.sweeps import audit_recent
from csmarket.modules.skins.api import trade_client

log = get_logger("csmarket.scheduler.trades_audit")

JOB_ID = "trades.audit"
#: A run the scheduler missed (it was down at 23:30) still runs within this window.
MISFIRE_GRACE_SECONDS = 3600


async def run() -> int | None:
    """One audit; ``None`` when skipped or on any failure (logged) — never raises.

    Returns:
        How many new divergences were recorded, or ``None``.
    """
    try:
        settings = get_settings()
        if not (settings.waxpeer_api_key or settings.waxpeer_fake):  # nothing to ask
            return None
        async with get_session_factory()() as db:
            return await audit_recent(db, trade_client(settings))
    except Exception:
        log.exception("trades.audit.crashed")
        return None


def register(scheduler: AsyncIOScheduler) -> None:
    """Every day at 23:30 UTC, coalesced."""
    scheduler.add_job(
        run,
        trigger="cron",
        hour=23,
        minute=30,
        id=JOB_ID,
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=MISFIRE_GRACE_SECONDS,
    )
