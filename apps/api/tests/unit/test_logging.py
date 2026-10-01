"""Structured logging: PII redaction (spec §11) and muted third-party URL loggers."""

from __future__ import annotations

import logging

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
