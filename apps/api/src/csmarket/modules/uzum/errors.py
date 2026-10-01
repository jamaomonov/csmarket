"""Uzum Bank Merchant API error catalogue.

On any business or transport failure we answer ``{"status": "FAILED", "errorCode": <int>,
...echo}``, where ``echo`` carries back whichever of ``serviceId`` / ``transId`` the request
supplied. This module only builds the body; the route wraps it in HTTP 400 (Uzum's contract:
"return HTTP 400 with an errorCode on any failure"). Pure — no I/O.
"""

from __future__ import annotations

from typing import Any


class UzumError(Exception):
    """A Uzum Merchant API error, raised by a handler and rendered on the wire.

    Attributes:
        code: The ``errorCode`` Uzum's spec assigns to this failure.
        message: Operator-facing English message.
        persist: Whether the route commits what the handler wrote before refusing (a
            transaction failed while refusing a second charge); otherwise it rolls back.
    """

    def __init__(self, code: int, message: str, *, persist: bool = False) -> None:
        """Initialise the error.

        Args:
            code: The Uzum ``errorCode``.
            message: Operator-facing English message.
            persist: Commit the handler's writes instead of rolling them back.
        """
        super().__init__(message)
        self.code = code
        self.message = message
        self.persist = persist

    def to_response(self, **echo: Any) -> dict[str, Any]:
        """The error body: ``{"status": "FAILED", "errorCode", **echo}``.

        Args:
            **echo: Request fields to echo back verbatim (``serviceId``, ``transId``).
        """
        return {"status": "FAILED", "errorCode": self.code, **echo}


def access_denied() -> UzumError:
    """10001: bad or missing Basic auth credentials."""
    return UzumError(10001, "Access denied")


def bad_json() -> UzumError:
    """10002: the body is not a JSON object."""
    return UzumError(10002, "JSON parsing error")


def invalid_operation() -> UzumError:
    """10003: the request was not an HTTP POST."""
    return UzumError(10003, "Invalid operation")


def missing_params() -> UzumError:
    """10005: a required parameter is missing or mistyped."""
    return UzumError(10005, "Missing required parameters")


def invalid_service_id() -> UzumError:
    """10006: ``serviceId`` is not ours."""
    return UzumError(10006, "Invalid serviceId")


def account_not_found() -> UzumError:
    """10007: no top-up has this number (Uzum: "additional payment attribute not found")."""
    return UzumError(10007, "Additional payment attribute not found")


def payment_already_made(*, persist: bool = False) -> UzumError:
    """10008: the top-up was already paid."""
    return UzumError(10008, "Payment already made", persist=persist)


def payment_cancelled() -> UzumError:
    """10009: the top-up cannot be paid (expired or reversed)."""
    return UzumError(10009, "Payment cancelled")


def transaction_already_created() -> UzumError:
    """10010: a transaction with this ``transId`` already exists."""
    return UzumError(10010, "Transaction with this transId already created")


def invalid_amount() -> UzumError:
    """10011: the amount (tiyin) is not the top-up's amount × 100."""
    return UzumError(10011, "Invalid amount")


def amount_below_minimum() -> UzumError:
    """10012: below the minimum (reserved; the top-up's own amount is checked instead)."""
    return UzumError(10012, "Amount below minimum")


def amount_above_maximum() -> UzumError:
    """10013: above the maximum (reserved; the top-up's own amount is checked instead)."""
    return UzumError(10013, "Amount exceeds maximum")


def transaction_not_found() -> UzumError:
    """10014: no transaction with this ``transId``."""
    return UzumError(10014, "Transaction transId does not exist")


def transaction_cancelled() -> UzumError:
    """10015: the transaction was reversed or failed and cannot be confirmed."""
    return UzumError(10015, "Transaction cancelled")


def transaction_already_confirmed() -> UzumError:
    """10016: the transaction was already confirmed."""
    return UzumError(10016, "Transaction already confirmed")


def transaction_cannot_be_cancelled() -> UzumError:
    """10017: cannot be reversed (ruling R7) — the top-up's money was already spent, or the
    payment was an order's (its skin is bought at payment)."""
    return UzumError(10017, "Transaction cannot be cancelled in current state")


def transaction_already_cancelled() -> UzumError:
    """10018: the transaction was already reversed."""
    return UzumError(10018, "Transaction already cancelled")


def internal_error() -> UzumError:
    """99999: an unexpected failure, including a failed commit."""
    return UzumError(99999, "Internal server error")


__all__ = [
    "UzumError",
    "access_denied",
    "account_not_found",
    "amount_above_maximum",
    "amount_below_minimum",
    "bad_json",
    "internal_error",
    "invalid_amount",
    "invalid_operation",
    "invalid_service_id",
    "missing_params",
    "payment_already_made",
    "payment_cancelled",
    "transaction_already_cancelled",
    "transaction_already_confirmed",
    "transaction_already_created",
    "transaction_cancelled",
    "transaction_cannot_be_cancelled",
    "transaction_not_found",
]
