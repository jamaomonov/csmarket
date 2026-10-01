"""Sandbox kassa credentials (Payme test key, Uzum sandbox pair) never credit in prod.

Outside prod they work as before; in prod they are ignored everywhere — webhook auth and
the storefront tile — unless ``CSMARKET_KASSA_SANDBOX_ENABLED`` opts in for the R14 sandbox
pass, which startup then warns about. Every credential here is fake.
"""

from __future__ import annotations

import base64
from collections.abc import Iterator

import pytest
from csmarket.bootstrap import warn_if_kassa_sandbox_in_prod
from csmarket.core.config import Settings, get_settings
from csmarket.modules.payme.routes import _is_authorized as payme_authorized
from csmarket.modules.payments.gateways.payme import PaymeGateway
from csmarket.modules.payments.gateways.uzum import UzumGateway
from csmarket.modules.uzum.routes import _is_authorized as uzum_authorized
from structlog.testing import capture_logs

PAYME_TEST_KEY = "fake-payme-sandbox-key"
PAYME_KEY = "fake-payme-cabinet-key"
UZUM_TEST = ("fake-uzum-test-login", "fake-uzum-test-pw")
UZUM_LIVE = ("fake-uzum-login", "fake-uzum-pw")


def _basic(login: str, secret: str) -> str:
    return "Basic " + base64.b64encode(f"{login}:{secret}".encode()).decode()


def _env(monkeypatch: pytest.MonkeyPatch, *, environment: str, opt_in: bool, live: bool) -> None:
    """Sandbox credentials always set; the production ones only when ``live``."""
    env = {
        "CSMARKET_ENVIRONMENT": environment,
        "CSMARKET_KASSA_SANDBOX_ENABLED": "true" if opt_in else "false",
        "CSMARKET_PAYME_MERCHANT_ID": "6a1faaca155c8e168e2a0000",
        "CSMARKET_PAYME_TEST_KEY": PAYME_TEST_KEY,
        "CSMARKET_PAYME_KEY": PAYME_KEY if live else "",
        "CSMARKET_UZUM_SERVICE_ID": "101202",
        "CSMARKET_UZUM_TEST_LOGIN": UZUM_TEST[0],
        "CSMARKET_UZUM_TEST_PASSWORD": UZUM_TEST[1],
        "CSMARKET_UZUM_LOGIN": UZUM_LIVE[0] if live else "",
        "CSMARKET_UZUM_PASSWORD": UZUM_LIVE[1] if live else "",
    }
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _clear_settings() -> Iterator[None]:
    yield
    get_settings.cache_clear()


def test_prod_ignores_sandbox_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    _env(monkeypatch, environment="prod", opt_in=False, live=False)
    settings = get_settings()
    assert settings.payme_keys() == ()
    assert settings.uzum_pairs() == ()
    assert payme_authorized(_basic("Paycom", PAYME_TEST_KEY)) is False
    assert uzum_authorized(_basic(*UZUM_TEST)) is False
    assert PaymeGateway().available is False
    assert UzumGateway().available is False


def test_prod_ignores_sandbox_credentials_beside_live_ones(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _env(monkeypatch, environment="prod", opt_in=False, live=True)
    assert payme_authorized(_basic("Paycom", PAYME_TEST_KEY)) is False
    assert uzum_authorized(_basic(*UZUM_TEST)) is False
    assert payme_authorized(_basic("Paycom", PAYME_KEY)) is True
    assert uzum_authorized(_basic(*UZUM_LIVE)) is True
    assert PaymeGateway().available is True
    assert UzumGateway().available is True


def test_prod_with_the_opt_in_accepts_sandbox_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _env(monkeypatch, environment="prod", opt_in=True, live=False)
    assert payme_authorized(_basic("Paycom", PAYME_TEST_KEY)) is True
    assert uzum_authorized(_basic(*UZUM_TEST)) is True
    assert PaymeGateway().available is True
    assert UzumGateway().available is True


@pytest.mark.parametrize("environment", ["dev", "test", "staging"])
def test_outside_prod_sandbox_credentials_work_without_the_opt_in(
    monkeypatch: pytest.MonkeyPatch, environment: str
) -> None:
    _env(monkeypatch, environment=environment, opt_in=False, live=False)
    assert get_settings().payme_keys() == (PAYME_TEST_KEY,)
    assert get_settings().uzum_pairs() == (UZUM_TEST,)
    assert payme_authorized(_basic("Paycom", PAYME_TEST_KEY)) is True
    assert uzum_authorized(_basic(*UZUM_TEST)) is True
    assert PaymeGateway().available is True
    assert UzumGateway().available is True


def test_the_opt_in_defaults_off() -> None:
    assert Settings().kassa_sandbox_enabled is False


def test_startup_warns_when_prod_opts_in() -> None:
    settings = Settings(
        environment="prod", kassa_sandbox_enabled=True, payme_test_key=PAYME_TEST_KEY
    )
    with capture_logs() as logs:
        assert warn_if_kassa_sandbox_in_prod(settings) is True
    assert [(e["event"], e["log_level"]) for e in logs] == [
        ("kassa.sandbox_enabled_in_prod", "warning")
    ]
    assert PAYME_TEST_KEY not in repr(logs)


@pytest.mark.parametrize(
    ("environment", "opt_in"), [("prod", False), ("dev", True), ("test", False)]
)
def test_startup_is_quiet_otherwise(environment: str, opt_in: bool) -> None:
    settings = Settings(environment=environment, kassa_sandbox_enabled=opt_in)  # type: ignore[arg-type]
    with capture_logs() as logs:
        assert warn_if_kassa_sandbox_in_prod(settings) is False
    assert logs == []
