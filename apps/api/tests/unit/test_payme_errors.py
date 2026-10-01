"""The Payme Merchant API error catalogue: exact codes, trilingual messages, wire shape."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from csmarket.modules.payme.errors import (
    PaymeError,
    account_busy,
    account_not_found,
    account_not_payable,
    bad_json,
    bad_rpc_fields,
    cannot_cancel_spent,
    fiscal_receipt_not_found,
    internal_error,
    invalid_amount,
    method_not_found,
    method_not_post,
    operation_not_permitted,
    transaction_not_found,
    unauthorized,
)

ACCOUNT_ERRORS: tuple[tuple[Callable[[], PaymeError], int], ...] = (
    (account_not_found, -31050),
    (account_not_payable, -31051),
    (account_busy, -31099),
)
OTHER_ERRORS: tuple[tuple[Callable[[], PaymeError], int], ...] = (
    (invalid_amount, -31001),
    (transaction_not_found, -31003),
    (cannot_cancel_spent, -31007),
    (operation_not_permitted, -31008),
    (unauthorized, -32504),
    (method_not_post, -32300),
    (bad_json, -32700),
    (bad_rpc_fields, -32600),
    (method_not_found, -32601),
    (internal_error, -32400),
    (fiscal_receipt_not_found, -32001),
)


@pytest.mark.parametrize(("factory", "code"), ACCOUNT_ERRORS + OTHER_ERRORS)
def test_factory_code_and_trilingual_message(factory: Callable[[], PaymeError], code: int) -> None:
    err = factory()
    assert isinstance(err, PaymeError)
    assert err.code == code
    assert set(err.message) == {"ru", "uz", "en"}
    assert all(err.message.values())
    assert err.persist is False


@pytest.mark.parametrize(("factory", "code"), ACCOUNT_ERRORS)
def test_account_range_errors_name_the_order_field(
    factory: Callable[[], PaymeError], code: int
) -> None:
    assert -31099 <= code <= -31050
    assert factory().data == "order"


@pytest.mark.parametrize(("factory", "code"), OTHER_ERRORS)
def test_other_errors_carry_no_field(factory: Callable[[], PaymeError], code: int) -> None:
    assert factory().data is None


@pytest.mark.parametrize(("factory", "code"), ACCOUNT_ERRORS + OTHER_ERRORS)
def test_uzbek_messages_use_the_okina_not_an_ascii_apostrophe(
    factory: Callable[[], PaymeError], code: int
) -> None:
    uz = factory().message["uz"]
    assert "'" not in uz
    assert "`" not in uz
    assert "‘" not in uz
    assert "’" not in uz


def test_to_rpc_error_shape() -> None:
    assert account_not_found().to_rpc_error() == {
        "code": -31050,
        "message": {"ru": "Заказ не найден", "uz": "Buyurtma topilmadi", "en": "Order not found"},
        "data": "order",
    }


def test_a_persisting_refusal_keeps_its_code() -> None:
    err = operation_not_permitted(persist=True)
    assert (err.code, err.persist) == (-31008, True)
    assert err.to_rpc_error()["code"] == -31008


def test_payme_error_is_raisable_with_the_english_text() -> None:
    with pytest.raises(PaymeError, match="Invalid amount") as exc_info:
        raise invalid_amount()
    assert exc_info.value.code == -31001


def test_constructor_direct() -> None:
    err = PaymeError(-1, {"ru": "р", "uz": "u", "en": "e"}, "x")
    assert err.to_rpc_error() == {
        "code": -1,
        "message": {"ru": "р", "uz": "u", "en": "e"},
        "data": "x",
    }
