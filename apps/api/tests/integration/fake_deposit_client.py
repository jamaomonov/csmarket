# apps/api/tests/integration/fake_deposit_client.py
"""A scripted Skinslink deposit client for the sales tests (no HTTP)."""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import replace
from decimal import Decimal

from csmarket.modules.skinslink.api import Deposit, Inventory, InventoryItem


def deposit(status: str = "active", **over: object) -> Deposit:
    """A Skinslink deposit report (``over`` replaces any field)."""
    base: dict[str, object] = {
        "id": 42,
        "merchant_tx_id": None,
        "status": status,
        "amount_usd": None,
        "bot_name": "Bot #3",
        "trade_offer_id": "6912345678",
        "offer_expiry_at": "2026-10-08T12:30:00Z",
        "hold_end_date": None,
        "fail_reason": None,
    }
    base.update(over)
    return Deposit(**base)  # type: ignore[arg-type]  # the test's own field values


def inv_item(
    asset_id: str, price: str, name: str = "AK-47 | Redline (Field-Tested)"
) -> InventoryItem:
    """An inventory card priced at ``price`` USD."""
    return InventoryItem(
        id=asset_id,
        name=name,
        price_usd=Decimal(price),
        image_url=f"https://img.test/{asset_id}.png",
        exterior="Field-Tested",
        rarity="Classified",
        rarity_color="#d32ce6",
    )


class FakeDepositClient:
    """``inventory``: answers popped per call (the last one repeats); ``created``: the
    create-deposit answer or exception; ``status``: the deposit-status answer or exception."""

    def __init__(
        self,
        *,
        inventory: Sequence[Inventory | BaseException] = (),
        created: Deposit | BaseException | None = None,
        status: Deposit | BaseException | None = None,
    ) -> None:
        self.inventories: deque[Inventory | BaseException] = deque(inventory)
        self.created = created
        self.status = status
        self.inventory_calls = 0
        self.deposit_calls: list[dict[str, object]] = []
        self.status_calls: list[str] = []

    async def inventory(self, *, partner: int, token: str) -> Inventory:
        self.inventory_calls += 1
        answer = self.inventories.popleft() if len(self.inventories) > 1 else self.inventories[0]
        if isinstance(answer, BaseException):
            raise answer
        return answer

    async def create_deposit(
        self,
        *,
        merchant_tx_id: str,
        partner: int,
        token: str,
        asset_ids: Sequence[str],
        min_prices: Mapping[str, Decimal],
    ) -> Deposit:
        self.deposit_calls.append(
            {
                "merchant_tx_id": merchant_tx_id,
                "asset_ids": list(asset_ids),
                "min_prices": dict(min_prices),
            }
        )
        if isinstance(self.created, BaseException):
            raise self.created
        assert self.created is not None, "script a create-deposit answer"
        return replace(self.created, merchant_tx_id=merchant_tx_id)

    async def deposit_status(self, *, merchant_tx_id: str) -> Deposit | None:
        self.status_calls.append(merchant_tx_id)
        if isinstance(self.status, BaseException):
            raise self.status
        return self.status
