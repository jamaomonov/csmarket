"""What an order really cost: the market's charge once it says, the agreed cost until then.

One rule for every reader (the admin order page, the dashboard, the analytics): Waxpeer's
``skin_trades.bought_units``, else the Skinslink / LIS-SKINS purchase's ``amount_units``
(USD × 1000), else ``orders.cost_usd`` from checkout.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import ColumnElement, func

from csmarket.modules.lisskins.api import LisskinsPurchase
from csmarket.modules.orders.models import Order, SkinTrade
from csmarket.modules.orders.purchase_rows import PurchaseRow
from csmarket.modules.skinslink.api import SkinslinkPurchase

_UNITS = Decimal(1000)


def spent(order: Order, trade: SkinTrade | None, bought: PurchaseRow | None) -> Decimal:
    """What the market charged, USD; the agreed cost until it says."""
    if trade is not None and trade.bought_units is not None:
        return Decimal(trade.bought_units) / _UNITS
    if bought is not None and bought.amount_units is not None:
        return Decimal(bought.amount_units) / _UNITS
    return order.cost_usd


def spent_usd_sql() -> ColumnElement[Decimal]:
    """:func:`spent` in SQL, for a statement outer-joining the trade and both purchases."""
    return func.coalesce(
        SkinTrade.bought_units / _UNITS,
        SkinslinkPurchase.amount_units / _UNITS,
        LisskinsPurchase.amount_units / _UNITS,
        Order.cost_usd,
    )


__all__ = ["spent", "spent_usd_sql"]
