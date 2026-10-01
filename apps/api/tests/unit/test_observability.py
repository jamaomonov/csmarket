"""``init_sentry`` must switch both of Sentry's privacy knobs off (AGENTS §9)."""

from __future__ import annotations

from typing import Any

import pytest
from csmarket.core.config import Settings
from csmarket.core.observability import init_sentry


@pytest.fixture
def captured_init(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    import sentry_sdk

    seen: dict[str, Any] = {}

    def _fake_init(**kwargs: Any) -> None:
        seen.update(kwargs)

    monkeypatch.setattr(sentry_sdk, "init", _fake_init)
    return seen


def test_both_privacy_switches_are_off(captured_init: dict[str, Any]) -> None:
    init_sentry(Settings(environment="dev", sentry_dsn="https://public@example.invalid/1"))
    assert captured_init["send_default_pii"] is False
    assert captured_init["include_local_variables"] is False
    assert captured_init["environment"] == "dev"
    assert captured_init["release"] == "csmarket-api"


def test_no_dsn_initialises_nothing(captured_init: dict[str, Any]) -> None:
    init_sentry(Settings(sentry_dsn=None))
    init_sentry(Settings(sentry_dsn=""))
    assert captured_init == {}


def test_non_asgi_services_get_no_request_integrations(captured_init: dict[str, Any]) -> None:
    init_sentry(Settings(sentry_dsn="https://public@example.invalid/1"), integrations="none")
    assert captured_init["integrations"] == []


def test_shutdown_cancellation_from_apscheduler_is_dropped() -> None:
    from csmarket.core.observability import _before_send

    event: Any = {
        "logger": "apscheduler.executors.default",
        "exception": {"values": [{"type": "CancelledError"}]},
    }
    assert _before_send(event, {}) is None
    other: Any = {
        "logger": "csmarket.worker",
        "exception": {"values": [{"type": "CancelledError"}]},
    }
    assert _before_send(other, {}) == other
