"""Email settings: the transport, Resend and sender defaults, and the prod guard."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from csmarket.bootstrap import missing_prod_settings
from csmarket.core.config import Settings, get_settings
from pydantic import ValidationError


@pytest.fixture(autouse=True)
def _clear_settings() -> Iterator[None]:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_defaults_are_the_dev_transport_and_our_sender() -> None:
    s = Settings()
    assert (s.email_transport, s.resend_api_key) == ("dev", "")
    assert s.resend_base_url == "https://api.resend.com"
    assert (s.email_from, s.email_from_name) == ("noreply@csmarket.uz", "CS Market")
    assert s.email_send_timeout_seconds == 10


def test_prod_refuses_the_dev_transport() -> None:
    with pytest.raises(ValidationError, match="CSMARKET_EMAIL_TRANSPORT"):
        Settings(environment="prod", email_transport="dev")


def test_prod_accepts_resend() -> None:
    assert Settings(environment="prod", email_transport="resend").email_transport == "resend"


def test_prod_without_a_transport_sends_through_resend() -> None:
    assert Settings(environment="prod").email_transport == "resend"


def test_prod_without_a_resend_key_is_reported_missing() -> None:
    s = Settings(environment="prod", email_transport="resend", resend_api_key="")
    assert "CSMARKET_RESEND_API_KEY" in missing_prod_settings(s)


def test_env_names_map_to_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CSMARKET_EMAIL_TRANSPORT", "resend")
    monkeypatch.setenv("CSMARKET_RESEND_API_KEY", "re_fake")
    assert (get_settings().email_transport, get_settings().resend_api_key) == (
        "resend",
        "re_fake",
    )
