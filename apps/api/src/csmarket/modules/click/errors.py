"""Click Shop API error catalogue.

Every Click answer is HTTP 200 with ``{"error": <int>, "error_note": <str>, ...echo}``;
``echo`` carries back whichever of ``click_trans_id`` / ``merchant_trans_id`` the request
supplied. This module is pure: it builds :class:`ClickError` instances with the exact code
and note Click's spec assigns, and the route renders them with :meth:`ClickError.to_response`.
Success (``0`` / ``Success``) is rendered by the handlers directly.
"""

from __future__ import annotations


class ClickError(Exception):
    """A Click Shop API error, raised by a handler and rendered on the wire.

    Attributes:
        code: The ``error`` code Click's spec assigns to this failure.
        note: The ``error_note`` sent with it.
        persist: Whether the route commits what the handler wrote before refusing (a
            transaction cancelled while refusing a second charge); otherwise it rolls back.
    """

    def __init__(self, code: int, note: str, *, persist: bool = False) -> None:
        """Initialise the error.

        Args:
            code: The Click ``error`` code.
            note: The ``error_note``.
            persist: Commit the handler's writes instead of rolling them back.
        """
        super().__init__(note)
        self.code = code
        self.note = note
        self.persist = persist

    def to_response(self, **echo: str) -> dict[str, int | str]:
        """The JSON body Click expects, with the request's identifiers echoed back.

        Args:
            **echo: Request fields to echo verbatim (``click_trans_id``,
                ``merchant_trans_id``).
        """
        return {"error": self.code, "error_note": self.note, **echo}


def sign_check_failed() -> ClickError:
    """-1: signature mismatch or an unknown service."""
    return ClickError(code=-1, note="SIGN CHECK FAILED!")


def incorrect_amount() -> ClickError:
    """-2: the amount is not the top-up's (or the prepared transaction's)."""
    return ClickError(code=-2, note="Incorrect parameter amount")


def action_not_found() -> ClickError:
    """-3: ``action`` is not this endpoint's (0 prepare, 1 complete)."""
    return ClickError(code=-3, note="Action not found")


def already_paid() -> ClickError:
    """-4: the top-up is already paid, or the transaction already confirmed."""
    return ClickError(code=-4, note="Already paid")


def user_not_found() -> ClickError:
    """-5: ``merchant_trans_id`` names no top-up."""
    return ClickError(code=-5, note="User does not exist")


def transaction_not_found() -> ClickError:
    """-6: ``merchant_prepare_id`` unknown, or it does not match the other identifiers."""
    return ClickError(code=-6, note="Transaction does not exist")


def failed_to_update() -> ClickError:
    """-7: an internal failure (including a failed commit)."""
    return ClickError(code=-7, note="Failed to update user")


def bad_request() -> ClickError:
    """-8: a malformed request (missing or non-numeric field, unparseable body, not POST)."""
    return ClickError(code=-8, note="Error in request from click")


def transaction_cancelled() -> ClickError:
    """-9: cancelled — the top-up cannot be paid, or Click aborted the transaction."""
    return ClickError(code=-9, note="Transaction cancelled")


__all__ = [
    "ClickError",
    "action_not_found",
    "already_paid",
    "bad_request",
    "failed_to_update",
    "incorrect_amount",
    "sign_check_failed",
    "transaction_cancelled",
    "transaction_not_found",
    "user_not_found",
]
