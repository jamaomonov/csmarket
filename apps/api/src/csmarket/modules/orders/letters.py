"""Order letters, enqueued in the transaction of the event they report (M4b T4, R5).

``receipt`` at ``mark_paid``, ``trade_sent`` when ``trades.apply`` moves the order to
``trade_sent``, ``refunded`` when ``refund_to_balance`` books a refund. The payload
snapshots what the letter shows — the number, the skin, a deadline or an amount — so the
worker renders it without reading orders. One letter per order and kind (a replay
enqueues nothing); whether it is sent is decided at send time (a verified address).
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.modules.notifications.api import enqueue
from csmarket.modules.orders.models import Order, SkinTrade


def _skin(order: Order) -> str:
    """The item as the order page names it: the market name, then the phase if any."""
    return f"{order.market_hash_name} · {order.phase}" if order.phase else order.market_hash_name


async def enqueue_receipt(db: AsyncSession, order: Order) -> None:
    """``Заказ оплачен`` for a just-paid order."""
    if order.channel == "api":
        return  # an API buyer is not mailed
    await enqueue(
        db,
        kind="receipt",
        user_id=order.user_id,
        order_id=order.id,
        payload={"number": order.number, "skin": _skin(order)},
    )


async def enqueue_trade_sent(
    db: AsyncSession,
    order: Order,
    trade: SkinTrade | None = None,
    *,
    send_until: datetime | None = None,
) -> None:
    """``Обмен отправлен``, with the offer's deadline when the market gave one (a Waxpeer
    ``trade``'s own, else ``send_until``)."""
    if order.channel == "api":
        return  # an API buyer is not mailed
    payload = {"number": order.number, "skin": _skin(order)}
    until = trade.send_until if trade is not None else send_until
    if until is not None:
        payload["send_until"] = until.astimezone(UTC).isoformat()
    await enqueue(db, kind="trade_sent", user_id=order.user_id, order_id=order.id, payload=payload)


async def enqueue_refunded(db: AsyncSession, order: Order) -> None:
    """``Деньги на балансе`` with the amount returned."""
    if order.channel == "api":
        return  # an API buyer is not mailed
    await enqueue(
        db,
        kind="refunded",
        user_id=order.user_id,
        order_id=order.id,
        payload={
            "number": order.number,
            "skin": _skin(order),
            "amount_uzs": f"{order.price_uzs:f}",
        },
    )
