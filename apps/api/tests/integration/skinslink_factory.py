"""Skinslink orders for the status and webhook tests."""

from __future__ import annotations

from decimal import Decimal

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
    **purchase: object,
) -> tuple[Order, SkinslinkPurchase]:
    """A kassa-paid Skinslink order in ``status`` and its purchase in ``purchase_status``
    (``purchase`` overrides any other column)."""
    order = await make_order(
        db,
        status=status,
        paid_with="payme",
        paid_at=clock.now(),
        price_uzs=PRICE,
        source="skinslink",
        offer_id="sl:100",
        listing_id=None,
    )
    values: dict[str, object] = {
        "order_id": order.id,
        "merchant_tx_id": order.id,
        "asset_id": "100",
        "paid_units": order.cost_units,
        "purchase_id": PURCHASE_ID,
        "status": purchase_status,
        "offer_id": OFFER,
        "buy_pending": False,
    }
    values.update(purchase)
    row = SkinslinkPurchase(**values)
    db.add(row)
    await db.commit()
    return order, row
