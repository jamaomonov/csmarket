"""LIS-SKINS orders for the status, reconcile and admin tests."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from csmarket.core import clock
from csmarket.modules.lisskins.models import LisskinsPurchase
from csmarket.modules.orders.models import Order
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.orders_factory import make_order

PRICE = Decimal(171_800)
#: A made-up Steam trade offer id.
OFFER = "7252638866"


async def make_lisskins_order(
    db: AsyncSession,
    *,
    status: str = "trade_sent",
    skin_status: str | None = "wait_accept",
    order: dict[str, object] | None = None,
    **purchase: object,
) -> tuple[Order, LisskinsPurchase]:
    """A kassa-paid LIS-SKINS order in ``status`` and its purchase with ``skin_status``
    (``order`` / ``purchase`` override any column)."""
    # Any: column values of any type, as ``make_order`` takes them.
    fields: dict[str, Any] = {
        "status": status,
        "paid_with": "payme",
        "paid_at": clock.now(),
        "price_uzs": PRICE,
        "source": "lisskins",
        "offer_id": "ls:125345",
        "listing_id": None,
        "cost_units": 12_340,
        **(order or {}),
    }
    row = await make_order(db, **fields)
    values: dict[str, object] = {
        "order_id": row.id,
        "custom_id": row.id,
        "skin_id": 125345,
        "paid_units": 12_340,
        "purchase_id": 55,
        "status": skin_status,
        "steam_trade_offer_id": OFFER if skin_status == "wait_accept" else None,
        "buy_pending": False,
    }
    values.update(purchase)
    p = LisskinsPurchase(**values)
    db.add(p)
    await db.commit()
    return row, p
