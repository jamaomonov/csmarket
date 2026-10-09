"""The order state machine (ruling R1) — the only place an order's status changes.

``pending``    created at checkout; waits for payment until ``expires_at``
``paid``       the money is ours; the worker buys next
``buying``     the worker holds the buy at Waxpeer
``trade_sent`` the seller sent the Steam offer
``delivered`` / ``cancelled`` / ``failed`` / ``returned`` are terminal.

``buying → delivered`` and ``buying → returned`` exist because one reconcile tick can see
Waxpeer jump from "bought" straight to accepted or returned. ``failed`` and ``returned``
come with the refund in the same transaction (R3's cases never reach them automatically).
"""

from __future__ import annotations

from csmarket.core.clock import now
from csmarket.core.errors import ConflictError
from csmarket.modules.orders.models import Order

#: The legal edges; a status absent from a set cannot be reached from that key.
TRANSITIONS: dict[str, frozenset[str]] = {
    "pending": frozenset({"paid", "cancelled"}),
    "paid": frozenset({"buying"}),
    "buying": frozenset({"trade_sent", "delivered", "failed", "returned"}),
    "trade_sent": frozenset({"delivered", "returned"}),
    "delivered": frozenset(),
    "cancelled": frozenset(),
    "failed": frozenset(),
    "returned": frozenset(),
}

#: The timestamp each target status stamps besides ``updated_at``.
_STAMP: dict[str, str] = {
    "paid": "paid_at",
    "trade_sent": "trade_sent_at",
    "delivered": "delivered_at",
    "cancelled": "cancelled_at",
    "failed": "failed_at",
    "returned": "failed_at",
}


class InvalidOrderTransitionError(ConflictError):
    """An order was asked to move along an edge the FSM does not have."""

    type_uri = "https://csmarket.uz/errors/invalid-order-transition"
    title = "Invalid order transition"


def move(order: Order, to: str) -> None:
    """Move ``order`` to ``to`` and stamp the matching timestamp.

    ``updated_at`` is stamped on every move; ``paid_at``, ``trade_sent_at``, ``delivered_at``,
    ``cancelled_at`` and ``failed_at`` (also for ``returned``) by their status.

    Args:
        order: The order row (locked by the caller).
        to: The target status.

    Raises:
        InvalidOrderTransitionError: ``to`` is not reachable from the current status; the
            order is left untouched.
    """
    if to not in TRANSITIONS.get(order.status, frozenset()):
        raise InvalidOrderTransitionError(
            f"order cannot go from {order.status} to {to}", code="invalid_order_transition"
        )
    at = now()
    order.status = to
    order.updated_at = at
    stamp = _STAMP.get(to)
    if stamp is not None:
        setattr(order, stamp, at)


__all__ = ["TRANSITIONS", "InvalidOrderTransitionError", "move"]
