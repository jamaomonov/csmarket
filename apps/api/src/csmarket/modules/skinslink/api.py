"""Public interface of the ``skinslink`` module — other modules import from here only."""

from __future__ import annotations

from csmarket.modules.skinslink.client import (
    LINK_ERROR_CODES,
    PURCHASE_FAIL_REASONS,
    AvailablePage,
    Balance,
    CatalogueEvent,
    CatalogueItem,
    EventsPage,
    Purchase,
    SkinslinkClient,
    SkinslinkError,
    SkinslinkForbiddenError,
    SkinslinkPurchaseClient,
    SkinslinkRateLimitedError,
    SkinslinkUnavailableError,
    client_for,
)

__all__ = [
    "LINK_ERROR_CODES",
    "PURCHASE_FAIL_REASONS",
    "AvailablePage",
    "Balance",
    "CatalogueEvent",
    "CatalogueItem",
    "EventsPage",
    "Purchase",
    "SkinslinkClient",
    "SkinslinkError",
    "SkinslinkForbiddenError",
    "SkinslinkPurchaseClient",
    "SkinslinkRateLimitedError",
    "SkinslinkUnavailableError",
    "client_for",
]
