"""Scheduler entrypoint. Run as ``python -m csmarket_scheduler.main``."""

from __future__ import annotations

import asyncio
import signal

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from csmarket.core.config import get_settings
from csmarket.core.logging import configure_logging, get_logger
from csmarket.core.observability import init_sentry

# Imported for their side effect: ``RefreshToken`` relates to ``User``, ``payments``' rows
# reference ``users``, ``orders`` and the wallet's, ``orders`` reference ``skin_items`` and
# ``fx_snapshots``, and ``click``'s, ``payme``'s and ``uzum``'s reference ``payments``, so
# every mapper must be registered before any job opens a session (AGENTS.md §4).
from csmarket.modules.auth import models as _auth_models  # noqa: F401
from csmarket.modules.click import models as _click_models  # noqa: F401
from csmarket.modules.fx import models as _fx_models  # noqa: F401
from csmarket.modules.lisskins import models as _lisskins_models  # noqa: F401
from csmarket.modules.notifications import models as _notifications_models  # noqa: F401
from csmarket.modules.orders import models as _orders_models  # noqa: F401
from csmarket.modules.payme import models as _payme_models  # noqa: F401
from csmarket.modules.payments import models as _payments_models  # noqa: F401
from csmarket.modules.skins import models as _skins_models  # noqa: F401
from csmarket.modules.skinslink import models as _skinslink_models  # noqa: F401
from csmarket.modules.users import models as _users_models  # noqa: F401
from csmarket.modules.uzum import models as _uzum_models  # noqa: F401
from csmarket.modules.wallet import models as _wallet_models  # noqa: F401

from csmarket_scheduler.jobs import (
    click_timeout,
    fx_refresh,
    orders_erase,
    orders_expiry,
    orders_health,
    payme_timeout,
    purge_refresh_tokens,
    skins_catalog_import,
    skins_price_sync,
    skinslink_balance,
    skinslink_mirror,
    skinslink_prices,
    skinslink_reconcile,
    topup_expiry,
    trades_audit,
    trades_protection,
    trades_reconcile,
    uzum_timeout,
)
from csmarket_scheduler.metrics import start_metrics_server

configure_logging()
log = get_logger("csmarket.scheduler")


def build_scheduler() -> AsyncIOScheduler:
    """The AsyncIO scheduler with every production job attached.

    Keep the body short: each ``jobs/<name>.register(scheduler)`` owns its own
    trigger and first-run stagger.
    """
    scheduler = AsyncIOScheduler(timezone="UTC")
    purge_refresh_tokens.register(scheduler)
    fx_refresh.register(scheduler)
    skins_catalog_import.register(scheduler)
    skins_price_sync.register(scheduler)
    skinslink_mirror.register(scheduler)
    skinslink_reconcile.register(scheduler)
    skinslink_balance.register(scheduler)
    skinslink_prices.register(scheduler)
    topup_expiry.register(scheduler)
    click_timeout.register(scheduler)
    payme_timeout.register(scheduler)
    uzum_timeout.register(scheduler)
    orders_expiry.register(scheduler)
    trades_reconcile.register(scheduler)
    trades_protection.register(scheduler)
    trades_audit.register(scheduler)
    orders_health.register(scheduler)
    orders_erase.register(scheduler)
    return scheduler


async def run() -> None:
    """Start the scheduler and block until SIGINT/SIGTERM."""
    init_sentry(get_settings(), integrations="none")
    start_metrics_server()
    scheduler = build_scheduler()
    scheduler.start()
    log.info("scheduler.started", jobs=[job.id for job in scheduler.get_jobs()])

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    await stop.wait()

    # ``wait=False``: ``wait=True`` is a promise AsyncIOExecutor cannot keep (its own
    # source says so) and every job here is periodic and re-runnable — a deploy
    # landing mid-tick cuts the job and the next tick redoes it. The resulting
    # CancelledError is dropped by ``core.observability._before_send``.
    scheduler.shutdown(wait=False)
    log.info("scheduler.stopped")


if __name__ == "__main__":
    asyncio.run(run())
