"""Uzum settings: env names map to ``Settings`` fields with the ``CSMARKET_`` prefix; a blank
service id is "not configured", not a startup crash."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from csmarket.core.config import get_settings


@pytest.fixture(autouse=True)
def _clear_settings() -> Iterator[None]:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_uzum_open_service_url_defaults_to_production() -> None:
    assert get_settings().uzum_open_service_url == "https://uzumbank.uz/open-service"


def test_uzum_credentials_default_to_blank() -> None:
    s = get_settings()
    assert s.uzum_service_id is None
    assert (s.uzum_login, s.uzum_password, s.uzum_test_login, s.uzum_test_password) == (
        "",
        "",
        "",
        "",
    )


@pytest.mark.parametrize(
    ("env", "field"),
    [
        ("CSMARKET_UZUM_LOGIN", "uzum_login"),
        ("CSMARKET_UZUM_PASSWORD", "uzum_password"),
        ("CSMARKET_UZUM_TEST_LOGIN", "uzum_test_login"),
        ("CSMARKET_UZUM_TEST_PASSWORD", "uzum_test_password"),
        ("CSMARKET_UZUM_OPEN_SERVICE_URL", "uzum_open_service_url"),
    ],
)
def test_uzum_settings_are_read_from_env(
    monkeypatch: pytest.MonkeyPatch, env: str, field: str
) -> None:
    monkeypatch.setenv(env, "fake-value-123")
    assert getattr(get_settings(), field) == "fake-value-123"


def test_uzum_service_id_parses_as_int(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CSMARKET_UZUM_SERVICE_ID", "101202")
    service_id = get_settings().uzum_service_id
    assert service_id == 101202
    assert isinstance(service_id, int)


def test_a_blank_uzum_service_id_is_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """Copying the ``CSMARKET_UZUM_SERVICE_ID=`` template line must not crash startup."""
    monkeypatch.setenv("CSMARKET_UZUM_SERVICE_ID", "")
    assert get_settings().uzum_service_id is None
