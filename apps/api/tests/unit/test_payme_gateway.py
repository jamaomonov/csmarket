"""``PaymeGateway``: available with the merchant id and either key; the checkout URL (R10)."""

from __future__ import annotations

import base64
from collections.abc import Iterator
from decimal import Decimal

import pytest
from csmarket.core.config import get_settings
from csmarket.modules.payments.api import available_providers, get_gateway
from csmarket.modules.payments.gateways import registry
from csmarket.modules.payments.gateways.payme import PaymeGateway
from csmarket.modules.payments.payable import Payable

_PAYABLE = Payable("topup", "T7K3M9QX", Decimal("5E+4"), "u", True, "ok", None)
_MERCHANT = "6a1faaca155c8e168e2a0000"


def _set(monkeypatch: pytest.MonkeyPatch, **env: str) -> None:
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _clear_settings() -> Iterator[None]:
    yield
    get_settings.cache_clear()


@pytest.fixture
def payme_env(monkeypatch: pytest.MonkeyPatch) -> None:
    _set(
        monkeypatch,
        CSMARKET_PAYME_MERCHANT_ID=_MERCHANT,
        CSMARKET_PAYME_TEST_KEY="fake-payme-test-key",
    )


def test_unavailable_without_credentials() -> None:
    assert PaymeGateway().available is False
    assert "payme" not in available_providers()


@pytest.mark.parametrize(
    "env",
    [
        {"CSMARKET_PAYME_KEY": "fake-key"},
        {"CSMARKET_PAYME_MERCHANT_ID": _MERCHANT},
        {"CSMARKET_PAYME_MERCHANT_ID": _MERCHANT, "CSMARKET_PAYME_KEY": ""},
    ],
)
def test_unavailable_without_the_merchant_id_or_any_key(
    monkeypatch: pytest.MonkeyPatch, env: dict[str, str]
) -> None:
    _set(monkeypatch, **env)
    assert PaymeGateway().available is False


@pytest.mark.parametrize("key", ["CSMARKET_PAYME_KEY", "CSMARKET_PAYME_TEST_KEY"])
def test_available_with_the_merchant_id_and_either_key(
    monkeypatch: pytest.MonkeyPatch, key: str
) -> None:
    _set(monkeypatch, CSMARKET_PAYME_MERCHANT_ID=_MERCHANT, **{key: "fake-payme-key"})
    assert PaymeGateway().available is True
    assert "payme" in available_providers()
    assert isinstance(get_gateway("payme"), PaymeGateway)


def test_offered_after_click_before_mock(monkeypatch: pytest.MonkeyPatch) -> None:
    _set(
        monkeypatch,
        CSMARKET_CLICK_MERCHANT_ID="5000",
        CSMARKET_CLICK_SERVICE_ID="108149",
        CSMARKET_CLICK_SECRET_KEY="fake-click-secret",
        CSMARKET_PAYME_MERCHANT_ID=_MERCHANT,
        CSMARKET_PAYME_KEY="fake-payme-key",
    )
    assert available_providers()[:2] == ["click", "payme"]


def test_registered_under_its_slug() -> None:
    gateway = registry()["payme"]
    assert isinstance(gateway, PaymeGateway)
    assert gateway.provider == "payme"


@pytest.mark.usefixtures("payme_env")
@pytest.mark.parametrize(
    ("locale", "back"),
    [
        ("ru", "http://localhost:3100/account/balance/topups/T7K3M9QX"),
        ("uz", "http://localhost:3100/uz/account/balance/topups/T7K3M9QX"),
        ("en", "http://localhost:3100/en/account/balance/topups/T7K3M9QX"),
    ],
)
def test_intent_url_is_the_payme_checkout_in_tiyin(locale: str, back: str) -> None:
    url = PaymeGateway().intent_url(payable=_PAYABLE, locale=locale)
    prefix = "https://checkout.paycom.uz/"
    assert url.startswith(prefix)
    params = base64.b64decode(url.removeprefix(prefix)).decode()
    assert params == f"m={_MERCHANT};ac.order=T7K3M9QX;a=5000000;c={back};l={locale}"


@pytest.mark.usefixtures("payme_env")
def test_intent_url_follows_the_sandbox_checkout_host(monkeypatch: pytest.MonkeyPatch) -> None:
    _set(monkeypatch, CSMARKET_PAYME_CHECKOUT_URL="https://test.paycom.uz/")
    url = PaymeGateway().intent_url(payable=_PAYABLE, locale="ru")
    assert url.startswith("https://test.paycom.uz/")
    assert "//" not in url.removeprefix("https://")


@pytest.mark.usefixtures("payme_env")
def test_intent_url_refuses_an_unknown_locale() -> None:
    with pytest.raises(ValueError, match="locale"):
        PaymeGateway().intent_url(payable=_PAYABLE, locale="de")
