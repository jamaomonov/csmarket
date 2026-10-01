"""``core.clock`` is the one source of "now"; tests may pin it."""

from __future__ import annotations

from datetime import UTC, datetime

from csmarket.core.clock import now, reset_clock, set_clock


def test_now_is_utc_aware() -> None:
    assert now().tzinfo is UTC


def test_set_and_reset_clock() -> None:
    pinned = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
    set_clock(lambda: pinned)
    try:
        assert now() == pinned
    finally:
        reset_clock()
    assert now() != pinned
