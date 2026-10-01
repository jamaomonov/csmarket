"""``UzumGateway``: available with the service id and a login/password pair; the open-service
link carries the number and our return page (R10), never the amount (Uzum prefills it from
``/check``)."""

from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal
from urllib.parse import parse_qs, urlsplit

import pytest
from csmarket.core.config import get_settings
from csmarket.modules.payments.api import available_providers, get_gateway
from csmarket.modules.payments.gateways import registry
from csmarket.modules.payments.gateways.uzum import UzumGateway
from csmarket.modules.payments.payable import Payable

_PAYABLE = Payable("topup", "T7K3M9QX", Decimal("5E+4"), "u", True, "ok", None)
_BLANK = {
    "CSMARKET_UZUM_SERVICE_ID": "",
    "CSMARKET_UZUM_LOGIN": "",
    "CSMARKET_UZUM_PASSWORD": "",
    "CSMARKET_UZUM_TEST_LOGIN": "",
    "CSMARKET_UZUM_TEST_PASSWORD": "",
}


def _set(monkeypatch: pytest.MonkeyPatch, **env: str) -> None:
    for key, value in {**_BLANK, **env}.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _clear_settings() -> Iterator[None]:
    yield
    get_settings.cache_clear()


@pytest.fixture
def uzum_env(monkeypatch: pytest.MonkeyPatch) -> None:
    _set(
        monkeypatch,
        CSMARKET_UZUM_SERVICE_ID="101202",
        CSMARKET_UZUM_TEST_LOGIN="fake-uzum-login",
        CSMARKET_UZUM_TEST_PASSWORD="fake-uzum-password",
    )


def test_unavailable_without_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    _set(monkeypatch)
    assert UzumGateway().available is False
    assert "uzum" not in available_providers()


@pytest.mark.parametrize(
    "env",
    [
        {"CSMARKET_UZUM_LOGIN": "l", "CSMARKET_UZUM_PASSWORD": "p"},  # no service id
        {"CSMARKET_UZUM_SERVICE_ID": "101202"},  # no pair
        {"CSMARKET_UZUM_SERVICE_ID": "101202", "CSMARKET_UZUM_LOGIN": "l"},  # half a pair
        {"CSMARKET_UZUM_SERVICE_ID": "101202", "CSMARKET_UZUM_PASSWORD": "p"},
        {"CSMARKET_UZUM_SERVICE_ID": "101202", "CSMARKET_UZUM_TEST_LOGIN": "l"},
        {"CSMARKET_UZUM_SERVICE_ID": "101202", "CSMARKET_UZUM_TEST_PASSWORD": "p"},
        # Halves of two different pairs do not make one.
        {
            "CSMARKET_UZUM_SERVICE_ID": "101202",
            "CSMARKET_UZUM_LOGIN": "l",
            "CSMARKET_UZUM_TEST_PASSWORD": "p",
        },
    ],
)
def test_unavailable_without_the_service_id_or_a_whole_pair(
    monkeypatch: pytest.MonkeyPatch, env: dict[str, str]
) -> None:
    _set(monkeypatch, **env)
    assert UzumGateway().available is False


@pytest.mark.parametrize("pair", ["", "TEST_"])
def test_available_with_the_service_id_and_either_pair(
    monkeypatch: pytest.MonkeyPatch, pair: str
) -> None:
    _set(
        monkeypatch,
        CSMARKET_UZUM_SERVICE_ID="101202",
        **{f"CSMARKET_UZUM_{pair}LOGIN": "fake-login", f"CSMARKET_UZUM_{pair}PASSWORD": "fake-pw"},
    )
    assert UzumGateway().available is True
    assert "uzum" in available_providers()
    assert isinstance(get_gateway("uzum"), UzumGateway)


def test_offered_after_click_and_payme_before_mock(monkeypatch: pytest.MonkeyPatch) -> None:
    _set(
        monkeypatch,
        CSMARKET_CLICK_MERCHANT_ID="5000",
        CSMARKET_CLICK_SERVICE_ID="108149",
        CSMARKET_CLICK_SECRET_KEY="fake-click-secret",
        CSMARKET_PAYME_MERCHANT_ID="6a1faaca155c8e168e2a0000",
        CSMARKET_PAYME_KEY="fake-payme-key",
        CSMARKET_UZUM_SERVICE_ID="101202",
        CSMARKET_UZUM_LOGIN="fake-login",
        CSMARKET_UZUM_PASSWORD="fake-pw",
    )
    assert available_providers()[:3] == ["click", "payme", "uzum"]


def test_registered_under_its_slug() -> None:
    gateway = registry()["uzum"]
    assert isinstance(gateway, UzumGateway)
    assert gateway.provider == "uzum"


@pytest.mark.usefixtures("uzum_env")
@pytest.mark.parametrize(
    ("locale", "back"),
    [
        ("ru", "http://localhost:3100/account/balance/topups/T7K3M9QX"),
        ("uz", "http://localhost:3100/uz/account/balance/topups/T7K3M9QX"),
        ("en", "http://localhost:3100/en/account/balance/topups/T7K3M9QX"),
    ],
)
def test_intent_url_is_the_open_service_link_without_an_amount(locale: str, back: str) -> None:
    url = UzumGateway().intent_url(payable=_PAYABLE, locale=locale)
    parts = urlsplit(url)
    assert f"{parts.scheme}://{parts.netloc}{parts.path}" == "https://uzumbank.uz/open-service"
    assert parse_qs(parts.query) == {
        "serviceId": ["101202"],
        "order": ["T7K3M9QX"],
        "redirectUrl": [back],
    }
    assert list(parse_qs(parts.query)) == ["serviceId", "order", "redirectUrl"]


@pytest.mark.usefixtures("uzum_env")
def test_intent_url_follows_the_configured_host(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CSMARKET_UZUM_OPEN_SERVICE_URL", "https://sandbox.example/open-service")
    get_settings.cache_clear()
    url = UzumGateway().intent_url(payable=_PAYABLE, locale="ru")
    assert url.startswith("https://sandbox.example/open-service?serviceId=101202&order=T7K3M9QX&")


@pytest.mark.usefixtures("uzum_env")
def test_intent_url_refuses_an_unknown_locale() -> None:
    with pytest.raises(ValueError, match="locale"):
        UzumGateway().intent_url(payable=_PAYABLE, locale="de")
