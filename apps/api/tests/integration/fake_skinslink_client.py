"""A scripted Skinslink purchase client for the worker tests."""

from __future__ import annotations

from collections import deque
from decimal import Decimal

from csmarket.modules.skinslink.api import Purchase


def purchase(status: str = "pending", **over: object) -> Purchase:
    """A Skinslink purchase report (``over`` replaces any field)."""
    base: dict[str, object] = {
        "id": 178,
        "merchant_tx_id": "o",
        "status": status,
        "offer_id": None,
        "fail_reason": None,
        "amount_usd": Decimal("12.345"),
        "asset_id": "100",
        "hold_end_date": None,
    }
    base.update(over)
    return Purchase(**base)  # type: ignore[arg-type]  # the test's own field values


class FakeSkinslinkClient:
    """``script``: answers (a :class:`Purchase`) or exceptions, popped per ``purchase`` call;
    ``statuses``: ``purchase_status`` answers by ``merchant_tx_id``."""

    def __init__(self, *script: object, statuses: dict[str, Purchase | None] | None = None) -> None:
        self.script = deque(script)
        self.statuses = statuses or {}
        self.calls: list[dict[str, object]] = []
        self.status_calls: list[str] = []

    async def purchase(
        self,
        *,
        asset_id: str,
        partner: int,
        token: str,
        merchant_tx_id: str,
        max_price_usd: Decimal,
    ) -> Purchase:
        """The next scripted answer."""
        self.calls.append(
            {"asset_id": asset_id, "merchant_tx_id": merchant_tx_id, "max_price_usd": max_price_usd}
        )
        nxt = self.script.popleft()
        if isinstance(nxt, BaseException):
            raise nxt
        assert isinstance(nxt, Purchase)
        return nxt

    async def purchase_status(self, *, merchant_tx_id: str) -> Purchase | None:
        """The configured report under ``merchant_tx_id``."""
        self.status_calls.append(merchant_tx_id)
        return self.statuses.get(merchant_tx_id)
