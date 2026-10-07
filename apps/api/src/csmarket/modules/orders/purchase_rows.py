"""Which row holds an order's buy, by ``orders.source``."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.modules.lisskins.api import LisskinsPurchase
from csmarket.modules.orders.models import Order, SkinTrade
from csmarket.modules.skins.api import parse_offer_id
from csmarket.modules.skinslink.api import SkinslinkPurchase

#: A non-Waxpeer order's purchase row (the attention columns are the same on both).
PurchaseRow = SkinslinkPurchase | LisskinsPurchase
#: Where each source keeps its pending buy (``buy_lease.take_lease``).
PENDING_TABLES: dict[str, type[SkinTrade] | type[SkinslinkPurchase] | type[LisskinsPurchase]] = {
    "waxpeer": SkinTrade,
    "skinslink": SkinslinkPurchase,
    "lisskins": LisskinsPurchase,
}


async def purchase_of(db: AsyncSession, order: Order, *, lock: bool) -> PurchaseRow | None:
    """A Skinslink or LIS-SKINS order's purchase, read fresh (``FOR UPDATE`` with ``lock``,
    after the order — ruling K); ``None`` for a Waxpeer order."""
    if order.source == "skinslink":
        sl = select(SkinslinkPurchase).where(SkinslinkPurchase.order_id == order.id)
        sl = sl.with_for_update() if lock else sl
        return await db.scalar(sl.execution_options(populate_existing=True))
    if order.source == "lisskins":
        ls = select(LisskinsPurchase).where(LisskinsPurchase.order_id == order.id)
        ls = ls.with_for_update() if lock else ls
        return await db.scalar(ls.execution_options(populate_existing=True))
    return None


def pending_buy(
    order: Order, *, units: int, key: str
) -> SkinTrade | SkinslinkPurchase | LisskinsPurchase:
    """The row that holds ``order``'s pending buy at its source, keyed ``key`` (Skinslink's
    ``merchant_tx_id``, LIS-SKINS' ``custom_id``; Waxpeer's ``project_id`` is the order id,
    which its lookup searches by; an older Waxpeer order carries no ``offer_id``)."""
    if order.source == "skinslink":
        _, raw = parse_offer_id(order.offer_id or "")
        return SkinslinkPurchase(
            order_id=order.id, merchant_tx_id=key, asset_id=raw, paid_units=units, buy_pending=True
        )
    if order.source == "lisskins":
        _, raw = parse_offer_id(order.offer_id or "")
        return LisskinsPurchase(
            order_id=order.id, custom_id=key, skin_id=int(raw), paid_units=units, buy_pending=True
        )
    return SkinTrade(
        order_id=order.id,
        project_id=order.id,
        listing_id=order.listing_id,
        paid_units=units,
        buy_pending=True,
        seller={},
    )


__all__ = ["PENDING_TABLES", "PurchaseRow", "pending_buy", "purchase_of"]
