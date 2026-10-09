"""The admin order actions' 409 codes and the refund lookup's time limit, shared by
``admin_actions`` (Waxpeer) and ``admin_refund_sources`` (Skinslink, LIS-SKINS)."""

from __future__ import annotations

from csmarket.core.errors import ConflictError

#: How long an admin refund waits for the market's lookup before refusing
#: (``waxpeer_unavailable`` / ``supplier_unavailable``) — the request path's 4 s (AGENTS §11).
REFUND_LOOKUP_SECONDS = 4.0

#: 409 codes of the admin actions → the problem's ``detail``.
CONFLICTS: dict[str, str] = {
    "already_refunded": "this order was already refunded",
    "order_in_flight": "the skin may still reach the buyer",
    "order_not_refundable": "this order has nothing to refund",
    "order_needs_attention": "this order waits for an admin's check",
    "order_busy": "a buy attempt is running for this order; try again in a few minutes",
    "not_retryable": "this order's buy cannot be retried now",
    "nothing_to_resolve": "this order's trade has no attention to resolve",
    "waxpeer_unavailable": "the purchase could not be checked at Waxpeer; try again later",
    "supplier_unavailable": (
        "the purchase could not be checked at Skinslink / LIS-SKINS; try again later"
    ),
}


def conflict(code: str) -> ConflictError:
    """The 409 for ``code`` (one of :data:`CONFLICTS`)."""
    return ConflictError(CONFLICTS[code], code=code)


__all__ = ["CONFLICTS", "REFUND_LOOKUP_SECONDS", "conflict"]
