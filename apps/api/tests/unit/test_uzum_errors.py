"""The Uzum error catalogue: every factory carries the ``errorCode`` Uzum's spec assigns, and
``to_response`` renders ``{"status": "FAILED", "errorCode", **echo}`` (the route wraps it in
HTTP 400)."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from csmarket.modules.uzum.errors import (
    UzumError,
    access_denied,
    account_not_found,
    amount_above_maximum,
    amount_below_minimum,
    bad_json,
    internal_error,
    invalid_amount,
    invalid_operation,
    invalid_service_id,
    missing_params,
    payment_already_made,
    payment_cancelled,
    transaction_already_cancelled,
    transaction_already_confirmed,
    transaction_already_created,
    transaction_cancelled,
    transaction_cannot_be_cancelled,
    transaction_not_found,
)

ALL_FACTORIES_AND_CODES: tuple[tuple[Callable[[], UzumError], int], ...] = (
    (access_denied, 10001),
    (bad_json, 10002),
    (invalid_operation, 10003),
    (missing_params, 10005),
    (invalid_service_id, 10006),
    (account_not_found, 10007),
    (payment_already_made, 10008),
    (payment_cancelled, 10009),
    (transaction_already_created, 10010),
    (invalid_amount, 10011),
    (amount_below_minimum, 10012),
    (amount_above_maximum, 10013),
    (transaction_not_found, 10014),
    (transaction_cancelled, 10015),
    (transaction_already_confirmed, 10016),
    (transaction_cannot_be_cancelled, 10017),
    (transaction_already_cancelled, 10018),
    (internal_error, 99999),
)


@pytest.mark.parametrize(("factory", "code"), ALL_FACTORIES_AND_CODES)
def test_factory_code(factory: Callable[[], UzumError], code: int) -> None:
    err = factory()
    assert isinstance(err, UzumError)
    assert err.code == code
    assert err.message
    assert err.persist is False


def test_codes_are_unique() -> None:
    codes = [code for _, code in ALL_FACTORIES_AND_CODES]
    assert len(codes) == len(set(codes))


def test_payment_already_made_can_persist() -> None:
    """A refused second charge at ``/confirm`` keeps the FAILED transaction (route commits)."""
    assert payment_already_made(persist=True).persist is True


def test_to_response_shape() -> None:
    r = invalid_amount().to_response(serviceId=101202, transId="t")
    assert r == {"status": "FAILED", "errorCode": 10011, "serviceId": 101202, "transId": "t"}


def test_to_response_no_echo() -> None:
    assert internal_error().to_response() == {"status": "FAILED", "errorCode": 99999}


def test_uzum_error_is_raisable() -> None:
    with pytest.raises(UzumError) as exc_info:
        raise invalid_amount()
    assert exc_info.value.code == 10011
    assert str(exc_info.value) == "Invalid amount"


def test_uzum_error_constructor_direct() -> None:
    err = UzumError(1, "custom message")
    assert (err.code, err.message, err.persist) == (1, "custom message", False)
    assert err.to_response() == {"status": "FAILED", "errorCode": 1}
