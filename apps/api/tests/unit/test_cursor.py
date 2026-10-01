"""The shared ``(created_at, id)`` keyset cursor round-trips and refuses garbage with a 422."""

import base64
from datetime import UTC, datetime

import pytest
from csmarket.core.cursor import decode_cursor, encode_cursor
from csmarket.core.errors import ValidationError

_ID = "01a0e6aa-0000-7000-8000-000000000001"
_STAMP = datetime(2026, 10, 1, 12, 30, 5, 123456, tzinfo=UTC)


def test_round_trips_the_timestamp_and_the_id() -> None:
    assert decode_cursor(encode_cursor(_STAMP, _ID)) == (_STAMP, _ID)


def test_token_is_url_safe_and_unpadded() -> None:
    token = encode_cursor(_STAMP, _ID)
    assert "=" not in token
    assert token == base64.urlsafe_b64encode(
        base64.urlsafe_b64decode(token + "==")
    ).decode().rstrip("=")


@pytest.mark.parametrize(
    "raw",
    [
        b"not json",
        b"[]",
        b'["2026-10-01T00:00:00+00:00"]',
        b'["not-a-date","01a0e6aa-0000-7000-8000-000000000001"]',
        b'["2026-10-01T00:00:00+00:00","not-a-uuid"]',
        b'["2026-10-01T00:00:00+00:00",5]',
        b"{}",
        b"\xff\xfe",
    ],
)
def test_garbage_is_a_validation_error(raw: bytes) -> None:
    token = base64.urlsafe_b64encode(raw).decode().rstrip("=")
    with pytest.raises(ValidationError) as caught:
        decode_cursor(token)
    assert caught.value.extra == {"code": "cursor"}


@pytest.mark.parametrize("token", ["", "!!!", "a"])
def test_a_token_we_did_not_issue_is_a_validation_error(token: str) -> None:
    with pytest.raises(ValidationError):
        decode_cursor(token)
