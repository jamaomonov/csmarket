"""Scripted LIS-SKINS clients for the orders tests."""

from __future__ import annotations

from collections import deque
from collections.abc import Sequence
from decimal import Decimal

from csmarket.modules.lisskins.api import Availability, Purchase, PurchasedSkin


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


def skin(status: str = "processing", **over: object) -> PurchasedSkin:
    """A LIS-SKINS skin report (``over`` replaces any field)."""
    base: dict[str, object] = {
        "id": 125345,
        "price_usd": Decimal("12.34"),
        "status": status,
        "return_reason": None,
        "error": None,
        "offer_id": None,
        "offer_expiry_at": None,
    }
    base.update(over)
    return PurchasedSkin(**base)  # type: ignore[arg-type]  # the test's own field values


def purchase(
    status: str = "processing", *, custom_id: str = "o", purchase_id: int = 55, **skin_over: object
) -> Purchase:
    """A purchase of one skin in ``status``."""
    return Purchase(
        purchase_id=purchase_id, custom_id=custom_id, skins=(skin(status, **skin_over),)
    )


class FakeLisskinsClient:
    """``script``: ``buy`` answers (a :class:`Purchase`) or exceptions, popped per call;
    ``infos``: ``info`` answers by ``custom_id``; ``info_error``: raised by ``info``."""

    def __init__(
        self,
        *script: object,
        infos: dict[str, Purchase] | None = None,
        info_error: Exception | None = None,
    ) -> None:
        self.script = deque(script)
        self.infos = infos if infos is not None else {}
        self.info_error = info_error
        self.calls: list[dict[str, object]] = []
        self.info_calls: list[list[str]] = []

    async def buy(
        self, *, skin_id: int, partner: int, token: str, max_price_usd: Decimal, custom_id: str
    ) -> Purchase:
        """The next scripted answer."""
        self.calls.append(
            {"skin_id": skin_id, "custom_id": custom_id, "max_price_usd": max_price_usd}
        )
        nxt = self.script.popleft()
        if isinstance(nxt, BaseException):
            raise nxt
        assert isinstance(nxt, Purchase)
        return nxt

    async def info(self, *, custom_ids: Sequence[str]) -> list[Purchase]:
        """The configured purchases among ``custom_ids``."""
        self.info_calls.append(list(custom_ids))
        if self.info_error is not None:
            raise self.info_error
        return [self.infos[c] for c in custom_ids if c in self.infos]
