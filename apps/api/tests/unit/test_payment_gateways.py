"""The gateway registry and the dev ``mock`` gateway (rulings R10, R11)."""

from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal

import pytest
from csmarket.core.config import get_settings
from csmarket.core.errors import NotFoundError
from csmarket.modules.payments.api import available_providers, get_gateway, return_url
from csmarket.modules.payments.gateways.mock import MockGateway
from csmarket.modules.payments.payable import Payable

_PAYABLE = Payable("topup", "T7K3M9QX", Decimal(50000), "u", True, "ok", None)


@pytest.fixture
def prod(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("CSMARKET_ENVIRONMENT", "prod")
    get_settings.cache_clear()
    yield
    monkeypatch.undo()
    get_settings.cache_clear()


def test_mock_is_offered_outside_prod() -> None:
    # Kassas join the list only with their credentials (none in the test env); mock is last.
    assert available_providers()[-1] == "mock"
    assert isinstance(get_gateway("mock"), MockGateway)


@pytest.mark.usefixtures("prod")
def test_mock_is_never_offered_in_prod() -> None:
    assert "mock" not in available_providers()
    with pytest.raises(NotFoundError):
        get_gateway("mock")


@pytest.mark.usefixtures("prod")
def test_prod_offers_exactly_the_configured_kassas(monkeypatch: pytest.MonkeyPatch) -> None:
    assert available_providers() == []
    monkeypatch.setenv("CSMARKET_CLICK_MERCHANT_ID", "5000")
    monkeypatch.setenv("CSMARKET_CLICK_SERVICE_ID", "108149")
    monkeypatch.setenv("CSMARKET_CLICK_SECRET_KEY", "fake-click-secret")
    get_settings.cache_clear()
    assert available_providers() == ["click"]
    monkeypatch.setenv("CSMARKET_PAYME_MERCHANT_ID", "6a1faaca155c8e168e2a0000")
    monkeypatch.setenv("CSMARKET_PAYME_KEY", "fake-payme-key")
    get_settings.cache_clear()
    assert available_providers() == ["click", "payme"]


def test_an_unknown_provider_is_not_found() -> None:
    with pytest.raises(NotFoundError):
        get_gateway("paypal")


@pytest.mark.parametrize(
    ("locale", "url"),
    [
        ("ru", "http://localhost:3100/account/balance/topups/T7K3M9QX?mock=1"),
        ("uz", "http://localhost:3100/uz/account/balance/topups/T7K3M9QX?mock=1"),
        ("en", "http://localhost:3100/en/account/balance/topups/T7K3M9QX?mock=1"),
    ],
)
def test_mock_intent_is_the_topup_page(locale: str, url: str) -> None:
    assert get_gateway("mock").intent_url(payable=_PAYABLE, locale=locale) == url


def test_return_url_refuses_an_unknown_locale() -> None:
    with pytest.raises(ValueError, match="locale"):
        return_url("T7K3M9QX", "de")
