"""Every ``trades_reconcile_seconds`` (10 s): follow in-flight orders at Waxpeer (ruling R5).

The logic is ``orders.sweeps.reconcile``: due orders are looked up in one call and moved
(``trade_sent``, ``delivered``, ``returned`` + refund, or an attention); a buy still pending
is retried through the buy's own lease. A no-op without a Waxpeer key (or the dev fake).
"""

from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from csmarket.core.config import get_settings
from csmarket.core.db import get_session_factory
from csmarket.core.logging import get_logger
from csmarket.modules.orders.sweeps import reconcile
from csmarket.modules.skins.api import trade_client

from csmarket_scheduler.startup import first_run_after

log = get_logger("csmarket.scheduler.trades_reconcile")

JOB_ID = "trades.reconcile"


async def run() -> int | None:
    """One tick; ``None`` when skipped or on any failure (logged) — never raises.

    Returns:
        How many due orders were looked at, or ``None``.
    """
    try:
        settings = get_settings()
        if not (settings.waxpeer_api_key or settings.waxpeer_fake):  # nothing to ask
            return None
        return await reconcile(get_session_factory(), trade_client(settings), settings=settings)
    except Exception:
        log.exception("trades.reconcile.crashed")
        return None


def register(scheduler: AsyncIOScheduler) -> None:
    """Every ``trades_reconcile_seconds``; first run 240 s after start."""
    seconds = max(1, int(get_settings().trades_reconcile_seconds))
    scheduler.add_job(
        run,
        trigger="interval",
        seconds=seconds,
        id=JOB_ID,
        next_run_time=first_run_after(240),
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )
