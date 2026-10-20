"""An analytics window: Tashkent dates, ``until`` inclusive (spec 2026-10-19-analytics)."""

from __future__ import annotations

import calendar
import re
from datetime import date, datetime, time, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict

from csmarket.core.errors import ValidationError
from csmarket.modules.orders.api import TASHKENT

Channel = Literal["all", "site", "api"]
MAX_DAYS = 366
#: Past Steam's 7-day protection a day no longer moves.
SETTLED_AFTER = timedelta(days=8)
SHORT_TTL = 120
LONG_TTL = 3600
_MONTH = re.compile(r"^(\d{4})-(\d{2})$")


class Window(BaseModel):
    """``[since, until]`` in Tashkent days."""

    model_config = ConfigDict(frozen=True)

    since: date
    until: date

    @property
    def days(self) -> int:
        """How many days, both ends included."""
        return (self.until - self.since).days + 1

    @property
    def start(self) -> datetime:
        """00:00 Tashkent of ``since``."""
        return datetime.combine(self.since, time(0), tzinfo=TASHKENT)

    @property
    def end(self) -> datetime:
        """Exclusive: 00:00 Tashkent after ``until``."""
        return datetime.combine(self.until + timedelta(days=1), time(0), tzinfo=TASHKENT)

    def previous(self) -> Window:
        """The same length right before ``since``."""
        return Window(
            since=self.since - timedelta(days=self.days), until=self.since - timedelta(days=1)
        )

    def dates(self) -> list[date]:
        """Every day of the window, in order."""
        return [self.since + timedelta(days=n) for n in range(self.days)]

    def ttl(self, today: date) -> int:
        """Seconds to cache an answer: long once the window has settled."""
        return LONG_TTL if self.until + SETTLED_AFTER < today else SHORT_TTL


#: The shop's years: outside them ``previous()`` and ``end`` overflow ``date`` (a 500).
MIN_YEAR, MAX_YEAR = 2000, 2100


def parse_window(since: date, until: date) -> Window:
    """A checked window.

    Raises:
        ValidationError: ``analytics_window`` — backwards, longer than :data:`MAX_DAYS`, or
            outside :data:`MIN_YEAR`..:data:`MAX_YEAR`.
    """
    if not (MIN_YEAR <= since.year <= MAX_YEAR and MIN_YEAR <= until.year <= MAX_YEAR):
        raise ValidationError(
            f"the window must lie in {MIN_YEAR}..{MAX_YEAR}", code="analytics_window"
        )
    if until < since or (until - since).days + 1 > MAX_DAYS:
        raise ValidationError(
            f"the window must be 1..{MAX_DAYS} days with since <= until", code="analytics_window"
        )
    return Window(since=since, until=until)


def month_window(month: str) -> Window:
    """``YYYY-MM`` → its first to last day.

    Raises:
        ValidationError: ``analytics_month`` — not a ``YYYY-MM`` month.
    """
    found = _MONTH.match(month)
    if found is None or not 1 <= int(found[2]) <= 12 or not MIN_YEAR <= int(found[1]) <= MAX_YEAR:
        raise ValidationError("month must be YYYY-MM", code="analytics_month")
    year, number = int(found[1]), int(found[2])
    last = calendar.monthrange(year, number)[1]
    return Window(since=date(year, number, 1), until=date(year, number, last))


__all__ = ["MAX_DAYS", "Channel", "Window", "month_window", "parse_window"]
