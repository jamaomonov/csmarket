"""``analytics.window``: Tashkent dates, ``until`` inclusive, the previous period, the TTL."""

from __future__ import annotations

from datetime import date

import pytest
from csmarket.core.errors import ValidationError
from csmarket.modules.analytics.window import parse_window


def test_until_is_inclusive_and_the_previous_period_has_the_same_length() -> None:
    w = parse_window(date(2026, 10, 1), date(2026, 10, 7))
    assert w.days == 7
    prev = w.previous()
    assert (prev.since, prev.until) == (date(2026, 9, 24), date(2026, 9, 30))
    assert w.start.isoformat() == "2026-10-01T00:00:00+05:00"
    assert w.end.isoformat() == "2026-10-08T00:00:00+05:00"


@pytest.mark.parametrize(
    ("since", "until"),
    [(date(2025, 1, 1), date(2026, 1, 3)), (date(2026, 10, 2), date(2026, 10, 1))],
)
def test_a_window_past_366_days_or_backwards_is_refused(since: date, until: date) -> None:
    with pytest.raises(ValidationError) as e:
        parse_window(since, until)
    assert e.value.extra["code"] == "analytics_window"


def test_a_settled_window_is_cached_long() -> None:
    w = parse_window(date(2026, 9, 1), date(2026, 9, 30))
    assert w.ttl(date(2026, 10, 19)) == 3600
    assert w.ttl(date(2026, 10, 5)) == 120


def test_a_month_window_spans_the_whole_month() -> None:
    from csmarket.modules.analytics.window import month_window

    w = month_window("2028-02")
    assert (w.since, w.until) == (date(2028, 2, 1), date(2028, 2, 29))
    with pytest.raises(ValidationError):
        month_window("2026-13")
