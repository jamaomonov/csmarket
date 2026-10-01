"""``ClickGateway``: available only with all three credentials; the checkout URL (R10)."""

from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal
from urllib.parse import urlencode

import pytest
from csmarket.core.config import get_settings
from csmarket.modules.payments.api import available_providers, get_gateway
from csmarket.modules.payments.gateways import registry
from csmarket.modules.payments.gateways.click import ClickGateway
from csmarket.modules.payments.payable import Payable

_PAYABLE = Payable("topup", "T7K3M9QX", Decimal("5E+4"), "u", True, "ok", None)
_CREDS = {
    "CSMARKET_CLICK_MERCHANT_ID": "5000",
    "CSMARKET_CLICK_SERVICE_ID": "108149",
    "CSMARKET_CLICK_SECRET_KEY": "fake-click-secret",
}


def _set(monkeypatch: pytest.MonkeyPatch, **env: str) -> None:
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()


@pytest.fixture
def click_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    _set(monkeypatch, **_CREDS)
    yield
    monkeypatch.undo()
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _clear_settings() -> Iterator[None]:
    yield
    get_settings.cache_clear()


def test_unavailable_without_credentials() -> None:
    assert ClickGateway().available is False
    assert "click" not in available_providers()


@pytest.mark.parametrize("missing", sorted(_CREDS))
def test_unavailable_when_any_credential_is_blank(
    monkeypatch: pytest.MonkeyPatch, missing: str
) -> None:
    _set(monkeypatch, **{**_CREDS, missing: ""})
    assert ClickGateway().available is False


@pytest.mark.usefixtures("click_env")
def test_available_with_all_three_and_offered_first() -> None:
    assert ClickGateway().available is True
    assert available_providers()[0] == "click"
    assert isinstance(get_gateway("click"), ClickGateway)


def test_registered_under_its_slug() -> None:
    gateway = registry()["click"]
    assert isinstance(gateway, ClickGateway)
    assert gateway.provider == "click"


@pytest.mark.usefixtures("click_env")
@pytest.mark.parametrize(
    ("locale", "back"),
    [
        ("ru", "http://localhost:3100/account/balance/topups/T7K3M9QX"),
        ("uz", "http://localhost:3100/uz/account/balance/topups/T7K3M9QX"),
        ("en", "http://localhost:3100/en/account/balance/topups/T7K3M9QX"),
    ],
)
def test_intent_url_is_the_click_pay_page_in_soum(locale: str, back: str) -> None:
    query = urlencode(
        {
            "service_id": "108149",
            "merchant_id": "5000",
            "amount": "50000",
            "transaction_param": "T7K3M9QX",
            "return_url": back,
        }
    )
    url = ClickGateway().intent_url(payable=_PAYABLE, locale=locale)
    assert url == f"https://my.click.uz/services/pay?{query}"
