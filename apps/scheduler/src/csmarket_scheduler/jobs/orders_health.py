"""Every minute: set the order-health gauges the alerts read (ruling R14).

The logic is ``orders.health.measure``; this job times it and writes the gauges. Waxpeer's
balance is read on every 5th tick (the first one included) — the endpoint is rate-limited
and a balance moves slowly. A failed tick is logged and the gauges keep their last values.
"""

from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from csmarket.core.config import get_settings
from csmarket.core.db import get_session_factory
from csmarket.core.logging import get_logger
from csmarket.core.metrics import (
    set_orders_stuck,
    set_trades_attention,
    set_waxpeer_balance,
    set_waxpeer_balance_threshold,
)
from csmarket.modules.orders.api import Health, measure
from csmarket.modules.skins.api import TradeClient, trade_client

from csmarket_scheduler.startup import first_run_after

log = get_logger("csmarket.scheduler.orders_health")

JOB_ID = "orders.health"
#: The balance is read on ticks 1, 6, 11, … (a restart reads it on the first tick).
BALANCE_EVERY = 5

_ticks = 0


async def run() -> Health | None:
    """One tick; ``None`` (logged) on any failure — never raises.

    Returns:
        The reading, or ``None`` when the tick failed.
    """
    global _ticks
    try:
        settings = get_settings()
        read_balance = _ticks % BALANCE_EVERY == 0
        _ticks += 1
        client: TradeClient | None = None
        if read_balance and (settings.waxpeer_api_key or settings.waxpeer_fake):
            client = trade_client(settings)
        async with get_session_factory()() as db:
            health = await measure(db, client, settings=settings)
        set_orders_stuck("paid", health.paid_stuck)
        set_orders_stuck("buying", health.buying_stuck)
        set_orders_stuck("trade_sent_unpolled", health.trade_sent_unpolled)
        set_trades_attention(health.attention)
        threshold = float(settings.waxpeer_balance_alert_usd)
        if health.waxpeer_balance_usd is not None:
            set_waxpeer_balance(float(health.waxpeer_balance_usd), threshold)
        else:
            set_waxpeer_balance_threshold(threshold)
    except Exception:
        log.exception("orders.health.crashed")
        return None
    log.info(
        "orders.health.done",
        paid_stuck=health.paid_stuck,
        buying_stuck=health.buying_stuck,
        trade_sent_unpolled=health.trade_sent_unpolled,
        attention=health.attention,
    )
    return health


def register(scheduler: AsyncIOScheduler) -> None:
    """Every 60 s; first run 260 s after start (staggered from the other jobs)."""
    scheduler.add_job(
        run,
        trigger="interval",
        seconds=60,
        id=JOB_ID,
        next_run_time=first_run_after(260),
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )
