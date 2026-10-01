"""Structured logging: PII redaction (spec §11) and muted third-party URL loggers."""

from __future__ import annotations

import logging

import pytest
from csmarket.core.config import get_settings
from csmarket.core.logging import REDACTED_KEYS, _redact_pii, configure_logging, hash_short


def test_httpx_request_logging_is_muted() -> None:
    """httpx logs the full URL at INFO; Waxpeer passes its API key as a query param."""
    configure_logging()
    for name in ("httpx", "httpcore"):
        assert logging.getLogger(name).getEffectiveLevel() >= logging.WARNING, name


def test_the_spec_pii_list_is_on_the_blocklist() -> None:
    for key in (
        "steam_id",
        "email",
        "ip",
        "trade_link",
        "tradelink",
        "trade_url",
        "token",
        "partner",
    ):
        assert key in REDACTED_KEYS, key


def test_redact_masks_exact_keys_and_pii_stems() -> None:
    event = _redact_pii(
        None,
        "info",
        {
            "event": "auth.signin",
            "steam_id": "76561198000000000",
            "steamid64": "76561198000000000",
            "customer_email": "a@b.uz",
            "client_ip": "203.0.113.7",
            "trade_link": "https://steamcommunity.com/tradeoffer/new/?partner=1&token=x",
        },
    )
    for key in ("steam_id", "steamid64", "customer_email", "client_ip", "trade_link"):
        assert event[key] == "<redacted>", key


def test_redact_keeps_safe_keys() -> None:
    event = _redact_pii(
        None,
        "info",
        {"event": "order.paid", "order_number": "7K3M9QX2", "amount_uzs": "125000", "locale": "ru"},
    )
    assert event["order_number"] == "7K3M9QX2"
    assert event["amount_uzs"] == "125000"
    assert event["locale"] == "ru"


def test_hash_short_is_stable_and_opaque() -> None:
    assert hash_short("76561198000000000") == hash_short("76561198000000000")
    assert len(hash_short("x")) == 12
    assert "76561198" not in hash_short("76561198000000000")


def test_acquirer_secrets_never_reach_the_log_output(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Rendered by the real ``configure_logging`` chain, as it would reach stdout and Loki."""
    import structlog

    monkeypatch.setenv("CSMARKET_LOG_JSON", "true")
    get_settings.cache_clear()
    try:
        configure_logging()
        structlog.configure(cache_logger_on_first_use=False)
        structlog.get_logger("csmarket.payments").info(
            "payments.webhook",
            click_secret_key="s3cr3t-click",
            payme_key="k3y-payme",
            payme_test_key="t3st-payme",
            uzum_password="p4ss-uzum",
            uzum_test_password="t3st-uzum",
            authorization="Basic eC1zZWNyZXQ=",
            request_authorization_header="Basic eC1zZWNyZXQ=",
            amount_uzs="125000",
        )
    finally:
        structlog.configure(cache_logger_on_first_use=True)
        get_settings.cache_clear()
    out = capsys.readouterr().out
    assert "payments.webhook" in out
    for leaked in (
        "s3cr3t-click",
        "k3y-payme",
        "t3st-payme",
        "p4ss-uzum",
        "t3st-uzum",
        "Basic eC1z",
    ):
        assert leaked not in out, leaked
    assert '"amount_uzs": "125000"' in out
