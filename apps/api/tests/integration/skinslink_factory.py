"""Skinslink orders for the status and webhook tests."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from csmarket.core import clock
from csmarket.modules.orders.models import Order
from csmarket.modules.skinslink.models import SkinslinkPurchase
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.orders_factory import make_order

PRICE = Decimal(171_800)
PURCHASE_ID = 178
#: A made-up Steam trade offer id.
OFFER = "6912345678"


async def make_skinslink_order(
    db: AsyncSession,
    *,
    status: str = "trade_sent",
    purchase_status: str | None = "active",
    order: dict[str, object] | None = None,
    **purchase: object,
) -> tuple[Order, SkinslinkPurchase]:
    """A kassa-paid Skinslink order in ``status`` and its purchase in ``purchase_status``
    (``order`` / ``purchase`` override any column)."""
    # Any: column values of any type, as ``make_order`` takes them.
    fields: dict[str, Any] = {
        "status": status,
        "paid_with": "payme",
        "paid_at": clock.now(),
        "price_uzs": PRICE,
        "source": "skinslink",
        "offer_id": "sl:100",
        "listing_id": None,
        **(order or {}),
    }
    order_row = await make_order(db, **fields)
    values: dict[str, object] = {
        "order_id": order_row.id,
        "merchant_tx_id": order_row.id,
        "asset_id": "100",
        "paid_units": order_row.cost_units,
        "purchase_id": PURCHASE_ID,
        "status": purchase_status,
        "offer_id": OFFER,
        "buy_pending": False,
    }
    values.update(purchase)
    row = SkinslinkPurchase(**values)
    db.add(row)
    await db.commit()
    return order_row, row
