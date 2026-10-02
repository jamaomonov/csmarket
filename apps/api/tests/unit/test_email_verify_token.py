"""The email confirmation token: opaque, tamper-evident, valid 24 h (M4b T5, R7)."""

from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta

import pytest
from csmarket.core import clock
from csmarket.core.errors import ValidationError
from csmarket.modules.users.email_verify import VerifyClaim, make_token, read_token

USER = "0190f0e0-0000-7000-8000-000000000001"
EMAIL = "Buyer@Example.test"
NOW = datetime(2026, 10, 2, 12, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _pinned_clock() -> object:
    clock.set_clock(lambda: NOW)
    yield
    clock.reset_clock()


def test_a_token_reads_back_its_claim() -> None:
    expires = NOW + timedelta(hours=24)
    claim = read_token(make_token(USER, EMAIL, expires_at=expires))
    assert claim == VerifyClaim(user_id=USER, email="buyer@example.test", expires_at=expires)


def test_the_token_reveals_neither_the_address_nor_the_account() -> None:
    token = make_token(USER, EMAIL, expires_at=NOW + timedelta(hours=1))
    raw = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))
    for leak in (b"buyer", b"example", USER.encode(), USER[:8].encode()):
        assert leak not in raw
    assert all(c.isalnum() or c in "-_" for c in token)


def test_two_tokens_for_the_same_claim_differ() -> None:
    expires = NOW + timedelta(hours=1)
    assert make_token(USER, EMAIL, expires_at=expires) != make_token(
        USER, EMAIL, expires_at=expires
    )


@pytest.mark.parametrize(
    "mangle",
    [
        lambda t: t[:-2] + ("AA" if t[-2:] != "AA" else "BB"),
        lambda t: "A" + t[1:] if t[0] != "A" else "B" + t[1:],
        lambda t: t[: len(t) // 2],
        lambda _t: "",
        lambda _t: "not a token!",
        lambda _t: "x" * 5000,
    ],
    ids=["tail", "head", "truncated", "empty", "garbage", "huge"],
)
def test_tampered_or_expired_token_is_refused(mangle: object) -> None:
    token = make_token(USER, EMAIL, expires_at=NOW + timedelta(hours=1))
    with pytest.raises(ValidationError) as caught:
        read_token(mangle(token))  # type: ignore[operator]
    assert caught.value.extra["code"] == "email_token_invalid"


def test_an_expired_token_is_refused() -> None:
    token = make_token(USER, EMAIL, expires_at=NOW - timedelta(seconds=1))
    with pytest.raises(ValidationError) as caught:
        read_token(token)
    assert caught.value.extra["code"] == "email_token_expired"
