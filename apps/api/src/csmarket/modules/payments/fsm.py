"""The payment state machine (ruling R4) — the only place a payment's status changes.

``created``   the intent is issued; the kassa has not called yet
``pending``   the kassa holds a transaction (Click prepare, Payme create, Uzum create)
``succeeded`` money arrived; leaves only to ``refunded``, through ``hooks.reverse``
``failed`` / ``cancelled`` / ``refunded`` are terminal.

``created → succeeded`` is legal: a kassa may settle without an earlier call we saw.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Protocol

from csmarket.core.clock import now
from csmarket.core.errors import ConflictError

Status = Literal["created", "pending", "succeeded", "failed", "cancelled", "refunded"]

#: The legal edges; a status absent from a set cannot be reached from that key.
TRANSITIONS: dict[str, frozenset[str]] = {
    "created": frozenset({"pending", "succeeded", "failed", "cancelled"}),
    "pending": frozenset({"succeeded", "failed", "cancelled"}),
    "succeeded": frozenset({"refunded"}),
    "failed": frozenset(),
    "cancelled": frozenset(),
    "refunded": frozenset(),
}

#: Attempts a kassa may still move: what ``cancel_pending`` and ``ensure_attempt`` treat as live.
LIVE: frozenset[str] = frozenset({"created", "pending"})


class InvalidTransitionError(ConflictError):
    """An edge the FSM does not allow."""

    type_uri = "https://csmarket.uz/errors/invalid-payment-transition"
    title = "Invalid payment transition"


class _Movable(Protocol):
    """What :func:`move` needs of a payment (the ORM row, or a test stand-in)."""

    status: str
    updated_at: datetime
    succeeded_at: datetime | None


def move(payment: _Movable, to: Status) -> None:
    """Change ``payment.status`` along a legal edge, stamping the times.

    ``updated_at`` is stamped on every move; ``succeeded_at`` only on success (a refund
    keeps it, so "when was this paid" survives the reversal).

    Raises:
        InvalidTransitionError: ``to`` is not reachable from the current status; the
            payment is left untouched.
    """
    if to not in TRANSITIONS.get(payment.status, frozenset()):
        raise InvalidTransitionError(f"payment cannot go {payment.status} -> {to}")
    stamp = now()
    payment.status = to
    payment.updated_at = stamp
    if to == "succeeded":
        payment.succeeded_at = stamp


__all__ = ["LIVE", "TRANSITIONS", "InvalidTransitionError", "Status", "move"]
