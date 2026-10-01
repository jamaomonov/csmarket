"""Public interface of the ``orders`` module — other modules import from here only.

``orders`` builds on ``payments``, ``wallet``, ``skins``, ``users`` and ``fx``; ``payments``
reaches orders only through this file, so it must never import ``csmarket.modules.payments``
(``wallet`` imports neither).
"""

from __future__ import annotations

from csmarket.modules.orders.fsm import TRANSITIONS, InvalidOrderTransitionError, move
from csmarket.modules.orders.models import (
    ATTENTION_REASONS,
    FAILURE_REASONS,
    IN_FLIGHT,
    ORDER_STATUSES,
    TERMINAL,
    Order,
    SkinTrade,
)

#: ``NOTIFY`` channel the worker listens on for paid orders.
ORDERS_CHANNEL = "orders"

__all__ = [
    "ATTENTION_REASONS",
    "FAILURE_REASONS",
    "IN_FLIGHT",
    "ORDERS_CHANNEL",
    "ORDER_STATUSES",
    "TERMINAL",
    "TRANSITIONS",
    "InvalidOrderTransitionError",
    "Order",
    "SkinTrade",
    "move",
]
