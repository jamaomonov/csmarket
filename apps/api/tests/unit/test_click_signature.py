"""Click ``sign_string``: both MD5 formulas over the raw wire strings, the one-service
secret lookup and the constant-time, fail-closed compare. Every key here is fake."""

from __future__ import annotations

import hashlib
from collections.abc import Iterator

import pytest
from csmarket.core.config import get_settings
from csmarket.modules.click import signature

_SECRET = "fake-click-secret"


@pytest.fixture
def click_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("CSMARKET_CLICK_SERVICE_ID", "108149")
    monkeypatch.setenv("CSMARKET_CLICK_SECRET_KEY", _SECRET)
    get_settings.cache_clear()
    yield
    monkeypatch.undo()
    get_settings.cache_clear()


def test_prepare_sign_matches_hand_computed_md5() -> None:
    parts = ("123456789", "108149", "sUpEr-SeCrEt", "ord_0001", "1000.00", "0")
    sign_time = "2026-07-23 12:00:00"
    expected = hashlib.md5("".join((*parts, sign_time)).encode()).hexdigest()
    result = signature.prepare_sign(
        click_trans_id=parts[0],
        service_id=parts[1],
        secret=parts[2],
        merchant_trans_id=parts[3],
        amount=parts[4],
        action=parts[5],
        sign_time=sign_time,
    )
    assert result == expected
    # Pinned literal, computed outside this process from the same raw strings.
    assert result == "2043542acca0f997a40ebff461b9b6a8"


def test_complete_sign_puts_the_prepare_id_after_the_account() -> None:
    expected = hashlib.md5(
        "".join(
            ("123456789", "108149", "s", "T7K3M9QX", "42", "1000.00", "1", "2026-07-23 12:05:00")
        ).encode()
    ).hexdigest()
    result = signature.complete_sign(
        click_trans_id="123456789",
        service_id="108149",
        secret="s",
        merchant_trans_id="T7K3M9QX",
        merchant_prepare_id="42",
        amount="1000.00",
        action="1",
        sign_time="2026-07-23 12:05:00",
    )
    assert result == expected


def test_complete_sign_differs_from_the_prepare_id_tacked_on_the_end() -> None:
    kwargs = {
        "click_trans_id": "1",
        "service_id": "108149",
        "secret": "s",
        "merchant_trans_id": "T7K3M9QX",
        "amount": "1.00",
        "action": "1",
        "sign_time": "2026-07-23 00:00:00",
    }
    wrong_order = hashlib.md5(("".join(kwargs.values()) + "99").encode()).hexdigest()
    assert signature.complete_sign(merchant_prepare_id="99", **kwargs) != wrong_order


def test_the_amount_is_hashed_as_sent_not_reformatted() -> None:
    common = {
        "click_trans_id": "1",
        "service_id": "108149",
        "secret": "s",
        "merchant_trans_id": "T7K3M9QX",
        "action": "0",
        "sign_time": "t",
    }
    assert signature.prepare_sign(amount="1000.00", **common) != signature.prepare_sign(
        amount="1000", **common
    )


def test_verify_is_case_insensitive() -> None:
    digest = hashlib.md5(b"hello").hexdigest()
    assert signature.verify(digest, digest.upper()) is True
    assert signature.verify(digest.upper(), digest) is True


def test_verify_strips_whitespace_on_the_received_value() -> None:
    digest = hashlib.md5(b"hello").hexdigest()
    assert signature.verify(digest, f"  {digest}\n") is True


def test_verify_refuses_a_tampered_digest() -> None:
    digest = hashlib.md5(b"hello").hexdigest()
    tampered = ("0" if digest[0] != "0" else "1") + digest[1:]
    assert signature.verify(digest, tampered) is False


def test_verify_fails_closed_on_non_ascii_without_raising() -> None:
    digest = hashlib.md5(b"hello").hexdigest()
    assert signature.verify(digest, "héllo" + digest[5:]) is False


@pytest.mark.usefixtures("click_env")
def test_the_configured_service_gets_its_secret() -> None:
    assert signature.secret_for_service(108149) == _SECRET


@pytest.mark.usefixtures("click_env")
def test_another_service_gets_no_secret() -> None:
    assert signature.secret_for_service(108150) is None


def test_a_blank_secret_is_no_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CSMARKET_CLICK_SERVICE_ID", "108149")
    monkeypatch.setenv("CSMARKET_CLICK_SECRET_KEY", "")
    get_settings.cache_clear()
    try:
        assert signature.secret_for_service(108149) is None
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()


def test_no_service_configured_is_no_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CSMARKET_CLICK_SERVICE_ID", "")
    monkeypatch.setenv("CSMARKET_CLICK_SECRET_KEY", _SECRET)
    get_settings.cache_clear()
    try:
        assert signature.secret_for_service(108149) is None
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()
