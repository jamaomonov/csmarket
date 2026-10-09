"""An order's money arrived: :func:`mark_paid` moves it to ``paid`` and wakes the worker.

Called by ``payments.hooks.settle`` (a kassa), by the balance pay (ruling R8), each with
the order row locked, and by the public API's buy (``api_checkout``) on the order it has just
inserted. ``NOTIFY orders``, the buyer's nudge and the ``receipt`` letter go out
in the caller's transaction, so each lands only once the payment is committed. Imports
nothing from ``payments``.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.modules.orders.fsm import move
from csmarket.modules.orders.letters import enqueue_receipt
from csmarket.modules.orders.models import Order
from csmarket.modules.orders.webhook_events import emit_order_event
from csmarket.modules.realtime.api import nudge

#: ``NOTIFY`` channel the worker listens on for paid orders.
ORDERS_CHANNEL = "orders"


async def mark_paid(db: AsyncSession, order: Order, *, provider: str) -> None:
    """Move ``order`` ``pending`` → ``paid``, record who paid, and ``NOTIFY orders``.

    Args:
        db: Session; the caller holds the order ``FOR UPDATE`` and commits.
        order: The order, locked.
        provider: ``click``, ``payme``, ``uzum``, ``mock``, ``wallet`` or ``usd_wallet`` (the
            public API; stored in ``orders.paid_with``).

    Raises:
        InvalidOrderTransitionError: the order is not ``pending``; nothing is written and
            nothing is sent.
    """
    move(order, "paid")
    order.paid_with = provider
    await db.flush()
    await db.execute(select(func.pg_notify(ORDERS_CHANNEL, order.number)))
    await nudge(db, user_id=order.user_id, number=order.number)
    await enqueue_receipt(db, order)
    await emit_order_event(db, order=order, trade=None, purchase=None)


__all__ = ["ORDERS_CHANNEL", "mark_paid"]
