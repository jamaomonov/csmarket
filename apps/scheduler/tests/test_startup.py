"""A long-period job's first run lands soon after boot, never a whole period away."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from csmarket_scheduler.startup import first_run_after


def test_first_run_is_in_the_future_but_soon() -> None:
    at = first_run_after(45)
    delta = at - datetime.now(UTC)
    assert timedelta(seconds=40) < delta <= timedelta(seconds=45)
