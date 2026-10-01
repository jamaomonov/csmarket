"""The Click Shop API error catalogue: exact ``error`` / ``error_note`` pairs and wire shape."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from csmarket.modules.click.errors import (
    ClickError,
    action_not_found,
    already_paid,
    bad_request,
    failed_to_update,
    incorrect_amount,
    sign_check_failed,
    transaction_cancelled,
    transaction_not_found,
    user_not_found,
)

ALL_FACTORIES_AND_CODES_AND_NOTES = (
    (sign_check_failed, -1, "SIGN CHECK FAILED!"),
    (incorrect_amount, -2, "Incorrect parameter amount"),
    (action_not_found, -3, "Action not found"),
    (already_paid, -4, "Already paid"),
    (user_not_found, -5, "User does not exist"),
    (transaction_not_found, -6, "Transaction does not exist"),
    (failed_to_update, -7, "Failed to update user"),
    (bad_request, -8, "Error in request from click"),
    (transaction_cancelled, -9, "Transaction cancelled"),
)


@pytest.mark.parametrize(("factory", "code", "note"), ALL_FACTORIES_AND_CODES_AND_NOTES)
def test_factory_code_and_note(factory: Callable[[], ClickError], code: int, note: str) -> None:
    err = factory()
    assert isinstance(err, ClickError)
    assert err.code == code
    assert err.note == note
    assert err.persist is False


def test_to_response_shape() -> None:
    r = incorrect_amount().to_response(click_trans_id="1", merchant_trans_id="T7K3M9QX")
    assert r == {
        "error": -2,
        "error_note": "Incorrect parameter amount",
        "click_trans_id": "1",
        "merchant_trans_id": "T7K3M9QX",
    }


def test_to_response_no_echo() -> None:
    assert sign_check_failed().to_response() == {"error": -1, "error_note": "SIGN CHECK FAILED!"}


def test_click_error_is_raisable() -> None:
    with pytest.raises(ClickError) as exc_info:
        raise transaction_not_found()
    assert exc_info.value.code == -6


def test_a_persisting_error_keeps_its_code() -> None:
    """``persist`` asks the route to commit what the handler wrote before refusing."""
    err = ClickError(code=-4, note="Already paid", persist=True)
    assert err.persist is True
    assert err.to_response() == {"error": -4, "error_note": "Already paid"}
