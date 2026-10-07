"""Scripted LIS-SKINS clients for the orders tests."""

from __future__ import annotations

from collections.abc import Sequence

from csmarket.modules.lisskins.api import Availability


class FakeAvailability:
    """``check-availability``: the scripted :class:`Availability`, or the exception raised."""

    def __init__(self, answer: Availability | Exception) -> None:
        self.answer = answer
        self.calls: list[list[int]] = []

    async def check_availability(self, ids: Sequence[int]) -> Availability:
        """The scripted answer."""
        self.calls.append(list(ids))
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer
