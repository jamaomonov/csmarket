"""An order's trade as the admin «Обмены» table reads it, whatever the source.

One vocabulary for Waxpeer, Skinslink and LIS-SKINS, built on the buyer's and the partner's
views (``trade_view``, ``public_view``) — no new rule:

==============  ==========================================================================
``pending``     waits for payment
``buying``      ``paid`` / ``buying``
``sent``        ``trade_sent``, the buyer has not accepted (``public_view.is_accepted``)
``hold``        accepted while Steam's protection runs (:func:`protection_end` in the future;
                a Skinslink ``hold`` with no end date yet counts too)
``delivered``   ``delivered``, or accepted with the protection over
``refunded``    the money went back (``refunded_at``), whatever the status
``cancelled``   ``cancelled``
``failed_held`` ``failed`` / ``returned`` without a refund yet (held for a person)
==============  ==========================================================================

Each predicate has a SQL twin (:func:`in_protection_sql`, :data:`ACTIVE_SQL`,
:data:`OPEN_ATTENTION_SQL`) for the tabs and their counts; the twins read the outer-joined
``skin_trades``, ``skinslink_purchases`` and ``lisskins_purchases`` of the order.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from sqlalchemy import ColumnElement, and_, false, func, not_, or_

from csmarket.modules.lisskins.api import LisskinsPurchase
from csmarket.modules.orders.models import Order, SkinTrade
from csmarket.modules.orders.public_view import ACCEPTED, is_accepted
from csmarket.modules.skinslink.api import SkinslinkPurchase

TradeRowState = Literal[
    "pending", "buying", "sent", "hold", "delivered", "refunded", "cancelled", "failed_held"
]
Purchase = SkinslinkPurchase | LisskinsPurchase

#: Order statuses whose row state is the status alone (no refund yet).
_SETTLED: dict[str, TradeRowState] = {
    "pending": "pending",
    "cancelled": "cancelled",
    "failed": "failed_held",
    "returned": "failed_held",
}
#: Waxpeer's status of a sent offer (accepted once ``release_date`` is set).
_WX_SENT = 4


def protection_end(
    order: Order, trade: SkinTrade | None, purchase: Purchase | None
) -> datetime | None:
    """When Steam's protection of the accepted trade ends; ``None`` when none runs.

    Skinslink ``hold`` keeps the order ``trade_sent`` until ``completed``; a Waxpeer trade
    accepted (4 with ``release_date``, not released) has already moved it to ``delivered``.
    """
    if order.refunded_at is not None:
        return None
    if isinstance(purchase, SkinslinkPurchase):
        if order.status == "trade_sent" and purchase.status == "hold":
            return purchase.hold_end_date
        return None
    if (
        trade is not None
        and order.status in ("trade_sent", "delivered")
        and trade.status == _WX_SENT
        and trade.release_date is not None
        and not trade.is_released
    ):
        return trade.release_date
    return None


def _in_protection(
    order: Order, trade: SkinTrade | None, purchase: Purchase | None, now: datetime
) -> bool:
    end = protection_end(order, trade, purchase)
    if end is not None:
        return end > now
    # A Skinslink ``hold`` whose end Skinslink has not told us yet.
    return (
        isinstance(purchase, SkinslinkPurchase)
        and order.refunded_at is None
        and order.status == "trade_sent"
        and purchase.status == "hold"
    )


def row_state(
    order: Order, trade: SkinTrade | None, purchase: Purchase | None, now: datetime
) -> TradeRowState:
    """The order's trade in the table's one vocabulary (the module's table)."""
    if order.refunded_at is not None:
        return "refunded"
    settled = _SETTLED.get(order.status)
    if settled is not None:
        return settled
    if _in_protection(order, trade, purchase, now):
        return "hold"
    if order.status == "trade_sent" and not is_accepted(order, trade, purchase):
        return "sent"
    return "delivered" if order.status in ("trade_sent", "delivered") else "buying"


def open_attention(trade: SkinTrade | None, purchase: Purchase | None) -> str | None:
    """The order's attention waiting for an admin (set, not resolved), of any source."""
    for row in (trade, purchase):
        if row is not None and row.attention_reason is not None and row.resolved_at is None:
            return row.attention_reason
    return None


def in_protection_sql(now: datetime) -> ColumnElement[bool]:
    """:func:`row_state` ``== "hold"`` in SQL (``COALESCE``: outer-join NULLs read false)."""
    skinslink = and_(
        Order.status == "trade_sent",
        SkinslinkPurchase.status == "hold",
        or_(SkinslinkPurchase.hold_end_date.is_(None), SkinslinkPurchase.hold_end_date > now),
    )
    waxpeer = and_(
        Order.status.in_(("trade_sent", "delivered")),
        SkinTrade.status == _WX_SENT,
        SkinTrade.release_date > now,
        SkinTrade.is_released.is_(False),
    )
    return and_(Order.refunded_at.is_(None), func.coalesce(or_(skinslink, waxpeer), false()))


#: :func:`row_state` in ``("buying", "sent")`` in SQL: on its way to the buyer.
ACTIVE_SQL: ColumnElement[bool] = and_(
    Order.refunded_at.is_(None),
    or_(
        Order.status.in_(("paid", "buying")),
        and_(Order.status == "trade_sent", not_(ACCEPTED)),
    ),
)


def _open(
    table: type[SkinTrade] | type[SkinslinkPurchase] | type[LisskinsPurchase],
) -> ColumnElement[bool]:
    return and_(table.attention_reason.is_not(None), table.resolved_at.is_(None))


#: :func:`open_attention` is not ``None``, in SQL.
OPEN_ATTENTION_SQL: ColumnElement[bool] = func.coalesce(
    or_(_open(SkinTrade), _open(SkinslinkPurchase), _open(LisskinsPurchase)), false()
)


__all__ = [
    "ACTIVE_SQL",
    "OPEN_ATTENTION_SQL",
    "TradeRowState",
    "in_protection_sql",
    "open_attention",
    "protection_end",
    "row_state",
]
