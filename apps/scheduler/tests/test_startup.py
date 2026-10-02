"""A long-period job's first run lands soon after boot, never a whole period away."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from csmarket.core import config as cfg
from csmarket_scheduler.startup import first_run_after


def test_first_run_is_in_the_future_but_soon() -> None:
    at = first_run_after(45)
    delta = at - datetime.now(UTC)
    assert timedelta(seconds=40) < delta <= timedelta(seconds=45)


def test_a_dev_divisor_scales_the_first_run_down() -> None:
    delta = first_run_after(240, divisor=10) - datetime.now(UTC)
    assert timedelta(seconds=20) < delta <= timedelta(seconds=24)


def test_the_divisor_comes_from_the_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CSMARKET_SCHEDULER_FIRST_RUN_DIVISOR", "10")
    cfg.get_settings.cache_clear()
    try:
        delta = first_run_after(240) - datetime.now(UTC)
        assert timedelta(seconds=20) < delta <= timedelta(seconds=24)
    finally:
        monkeypatch.undo()
        cfg.get_settings.cache_clear()
