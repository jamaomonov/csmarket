"""Every 30 seconds: expire P2P requests past their ten minutes, release amounts whose
quarantine ended (their unpaid top-ups then expire), and report when the last HUMO
notification arrived (spec 2026-10-19-p2p-topup).

The logic is ``p2p.sweep_tick``; a failure is logged and the next tick retries.
"""

from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from csmarket.core.clock import now
from csmarket.core.db import get_session_factory
from csmarket.core.logging import get_logger
from csmarket.core.metrics import record_p2p_sweep
from csmarket.modules.p2p.api import sweep_tick

from csmarket_scheduler.startup import first_run_after

log = get_logger("csmarket.scheduler.p2p_sweep")

JOB_ID = "p2p.sweep"


async def _sweep_once() -> tuple[int, int]:
    async with get_session_factory()() as db:
        result, last = await sweep_tick(db, at=now())
        await db.commit()
    record_p2p_sweep(result.expired, last.timestamp() if last is not None else None)
    return result.expired, result.released


async def run() -> tuple[int, int] | None:
    """One sweep; ``None`` (logged) on any failure — never raises.

    Returns:
        ``(expired, released)``, or ``None`` when the sweep failed.
    """
    try:
        expired, released = await _sweep_once()
    except Exception:
        log.exception("p2p.sweep.crashed")
        return None
    if expired or released:
        log.info("p2p.sweep.done", expired=expired, released=released)
    return expired, released


def register(scheduler: AsyncIOScheduler) -> None:
    """Every 30 seconds; first run 440 s after start (staggered from the other jobs)."""
    scheduler.add_job(
        run,
        trigger="interval",
        seconds=30,
        id=JOB_ID,
        next_run_time=first_run_after(440),
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )


__all__ = ["JOB_ID", "register", "run"]
