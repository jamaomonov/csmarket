"""Payme settings: env names map to ``Settings`` fields with the ``CSMARKET_`` prefix."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from csmarket.core.config import get_settings


@pytest.fixture(autouse=True)
def _clear_settings() -> Iterator[None]:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_payme_login_defaults_to_paycom() -> None:
    assert get_settings().payme_login == "Paycom"


def test_payme_checkout_url_defaults_to_production() -> None:
    assert get_settings().payme_checkout_url == "https://checkout.paycom.uz"


def test_payme_keys_default_to_blank() -> None:
    s = get_settings()
    assert (s.payme_merchant_id, s.payme_key, s.payme_test_key) == ("", "", "")


@pytest.mark.parametrize(
    ("env", "field"),
    [
        ("CSMARKET_PAYME_MERCHANT_ID", "payme_merchant_id"),
        ("CSMARKET_PAYME_KEY", "payme_key"),
        ("CSMARKET_PAYME_TEST_KEY", "payme_test_key"),
        ("CSMARKET_PAYME_LOGIN", "payme_login"),
        ("CSMARKET_PAYME_CHECKOUT_URL", "payme_checkout_url"),
    ],
)
def test_payme_settings_are_read_from_env(
    monkeypatch: pytest.MonkeyPatch, env: str, field: str
) -> None:
    monkeypatch.setenv(env, "fake-value-123")
    assert getattr(get_settings(), field) == "fake-value-123"
