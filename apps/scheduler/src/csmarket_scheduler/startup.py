"""When a periodic job should first fire after the process starts.

APScheduler's ``interval`` trigger, given no ``next_run_time``, schedules the
first run one whole interval after ``add_job``. For a job that runs every
minute that is invisible. For an hourly one it means every restart pushes the
next run a full hour out — so a container that restarts more often than its
own period never runs the job at all, silently, with the scheduler up and the
job listed as registered.

That is not hypothetical: a deploy restarts every container, and a daily job
needs only one restart per day to never run.

So a long-period job gets an explicit first run shortly after boot. The delays
are staggered rather than shared: several of these jobs call the same upstream
APIs, and firing them together on every deploy turns a restart into a burst.

Dev and e2e may scale every delay down by ``CSMARKET_SCHEDULER_FIRST_RUN_DIVISOR``
(the dev compose sets 10: the reconcile sweep runs ~24 s after ``make dev``
instead of 4 min). ``Settings`` refuses any divisor but 1 in prod.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from csmarket.core.config import get_settings


def first_run_after(seconds: int, *, divisor: int | None = None) -> datetime:
    """A ``next_run_time`` ``seconds`` from now, divided by the dev first-run divisor.

    Deliberately not "now": a container that crash-loops faster than this
    would otherwise re-run the job on every attempt, and these jobs talk to
    paid upstreams.

    Args:
        seconds: The delay in production.
        divisor: Overrides ``settings.scheduler_first_run_divisor`` (1 in prod).
    """
    scale = divisor if divisor is not None else get_settings().scheduler_first_run_divisor
    return datetime.now(UTC) + timedelta(seconds=seconds / scale)


__all__ = ["first_run_after"]
