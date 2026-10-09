"""API order events for the partner's webhook, enqueued in the transaction of the move.

The row and its ``NOTIFY api_webhooks`` ride the event's transaction: both land on commit,
or neither does. A delivery is unique per ``(order, event)``, so a replayed report or a
second pass of a sweep enqueues nothing new. The payload is the public order view, so it
never names the supplier or carries the trade link. Only ``channel == "api"`` orders of a
user with a webhook produce a row; every other order costs no query.
"""

from __future__ import annotations

from typing import Final

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.clock import now
from csmarket.core.ids import new_id
from csmarket.modules.orders.models import Order, SkinTrade
from csmarket.modules.orders.public_view import Purchase, public_order, public_status
from csmarket.modules.public_api.models import ApiWebhook, ApiWebhookDelivery

#: The LISTEN channel of the worker's webhook queue.
WEBHOOKS_CHANNEL: Final = "api_webhooks"

#: The partner status the order reads now → the event that reports it.
_EVENTS: Final = {
    "buying": "order.paid",
    "trade_sent": "order.trade_sent",
    "delivered": "order.delivered",
    "refunded": "order.refunded",
}


async def emit_order_event(
    db: AsyncSession, *, order: Order, trade: SkinTrade | None, purchase: Purchase | None
) -> None:
    """Enqueue the event for ``order``'s current public status. Flushes, never commits.

    A no-op for a site order and for an API order whose user has no webhook.

    Args:
        db: The session of the move the event reports.
        order: The order, already moved.
        trade: Its ``skin_trades`` row, if the caller holds one.
        purchase: Its Skinslink / LIS-SKINS purchase, if the caller holds one.
    """
    if order.channel != "api":
        return
    if await db.get(ApiWebhook, order.user_id) is None:
        return
    event = _EVENTS[public_status(order, trade, purchase)]
    event_id = new_id()
    payload = {
        "event": event,
        "event_id": event_id,
        "created_at": now().isoformat(),
        "order": public_order(order, trade, purchase).model_dump(mode="json"),
    }
    stmt = (
        insert(ApiWebhookDelivery)
        .values(id=event_id, user_id=order.user_id, order_id=order.id, event=event, payload=payload)
        .on_conflict_do_nothing(index_elements=["order_id", "event"])
        .returning(ApiWebhookDelivery.id)
    )
    row_id = await db.scalar(stmt)
    if row_id is not None:
        await db.execute(select(func.pg_notify(WEBHOOKS_CHANNEL, str(row_id))))


__all__ = ["WEBHOOKS_CHANNEL", "emit_order_event"]
