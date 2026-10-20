"""Catalogue cursors round-trip exactly and refuse garbage with a 422."""

import base64
from decimal import Decimal

import pytest
from csmarket.core.errors import ValidationError
from csmarket.modules.skins.service import decode_cursor, encode_cursor


def test_cursor_round_trips_value_and_id() -> None:
    token = encode_cursor(27867, "01a0e6aa-0000-7000-8000-000000000001")
    assert decode_cursor(token) == (27867, "01a0e6aa-0000-7000-8000-000000000001")


def test_cursor_round_trips_none_value_for_unpriced_rows() -> None:
    assert decode_cursor(encode_cursor(None, "x")) == (None, "x")


def test_garbage_cursor_is_a_validation_error() -> None:
    with pytest.raises(ValidationError):
        decode_cursor("not-a-cursor")


def test_cursor_round_trips_a_decimal_price_exactly() -> None:
    token = encode_cursor(Decimal("30.37"), "x")
    assert decode_cursor(token) == (Decimal("30.37"), "x")


@pytest.mark.parametrize(
    "payload",
    [
        b'[true,"x"]',  # a bool is not a sort value
        b"[1,2]",  # the id must be a string
        b'["not-a-number","x"]',
        b'[[1],"x"]',
        # Review 2026-10-20: past int64 (asyncpg overflow) or not a number — 422, not 500.
        b'[100000000000000000000,"x"]',
        b'[-100000000000000000000,"x"]',
        b'["NaN","x"]',
        b'["Infinity","x"]',
    ],
)
def test_well_formed_but_wrong_cursors_are_validation_errors(payload: bytes) -> None:
    token = base64.urlsafe_b64encode(payload).decode().rstrip("=")
    with pytest.raises(ValidationError):
        decode_cursor(token)


def test_a_negative_discount_cursor_round_trips() -> None:
    """The discount sort pages below zero (Steam cheaper than us)."""
    assert decode_cursor(encode_cursor(-12, "x")) == (-12, "x")
    assert decode_cursor(encode_cursor(Decimal("-3.5"), "x")) == (Decimal("-3.5"), "x")
