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


def test_request_bodies_are_never_attached(captured_init: dict[str, Any]) -> None:
    """A card number in a ``POST /sell`` body must not reach Sentry on a 500."""
    init_sentry(Settings(sentry_dsn="https://public@example.invalid/1"))
    assert captured_init["max_request_body_size"] == "never"


def test_before_send_drops_a_request_body() -> None:
    from csmarket.core.observability import _before_send

    event: Any = {"request": {"url": "/x", "data": {"number": "8600123412341234"}}}
    out = _before_send(event, {})
    assert out is not None
    assert "data" not in out["request"]


def test_outgoing_query_strings_never_reach_sentry(monkeypatch: pytest.MonkeyPatch) -> None:
    """Waxpeer takes its key and the buyer's trade-link token in the query string.

    sentry-sdk's httpx integration records the raw query of every outgoing call in breadcrumbs,
    and the next error event of that process ships them. Real SDK, real httpx, a capturing
    transport: neither the fake key nor the fake token may appear in what would be sent.
    """
    import httpx
    import respx
    import sentry_sdk
    from sentry_sdk.envelope import Envelope
    from sentry_sdk.transport import Transport

    sent: list[bytes] = []

    class _Capture(Transport):
        def capture_envelope(self, envelope: Envelope) -> None:
            sent.append(envelope.serialize())

    real_init = sentry_sdk.init

    def _init(**kwargs: Any) -> Any:
        return real_init(transport=_Capture, **kwargs)

    monkeypatch.setattr(sentry_sdk, "init", _init)
    init_sentry(
        Settings(sentry_dsn="https://public@example.invalid/1", sentry_traces_sample_rate=1.0),
        integrations="none",
    )
    try:

        async def _call() -> None:
            with respx.mock:
                respx.get("https://api.example.invalid/v1/buy").respond(200, json={})
                async with httpx.AsyncClient() as client:
                    with sentry_sdk.start_transaction(name="t"):
                        await client.get(
                            "https://api.example.invalid/v1/buy",
                            params={"api": "FAKEKEY123", "token": "FAKETOKEN9"},
                        )

        import asyncio

        asyncio.run(_call())
        sentry_sdk.capture_message("boom")
        sentry_sdk.flush()
    finally:
        real_init()  # back to the no-op client for the rest of the session

    blob = b"".join(sent)
    assert blob, "the capturing transport saw nothing; the test proves nothing"
    assert b"FAKEKEY123" not in blob
    assert b"FAKETOKEN9" not in blob


def test_before_send_drops_an_incoming_query_string() -> None:
    """The Steam sign-in callback carries the Steam ID in its query (``openid.claimed_id``)."""
    from csmarket.core.observability import _before_send

    event: Any = {"request": {"url": "/x", "query_string": "openid.claimed_id=7656119"}}
    out = _before_send(event, {})
    assert out is not None
    assert "query_string" not in out["request"]


def test_before_send_drops_request_headers_and_cookies() -> None:
    """Headers carry the storefront secret, the visitor's IP and ``Cf-Connecting-Ip``."""
    from csmarket.core.observability import _before_send

    event: Any = {
        "request": {
            "url": "/x",
            "headers": {"X-Storefront-Secret": "s3cret", "X-Storefront-Client-Ip": "203.0.113.9"},
            "cookies": {"refresh": "r"},
            "env": {"REMOTE_ADDR": "203.0.113.9"},
        }
    }
    out = _before_send(event, {})
    assert out is not None
    assert {"headers", "cookies", "env"}.isdisjoint(out["request"])


def test_before_send_strips_urls_from_exception_values() -> None:
    """``httpx.HTTPStatusError`` puts the full URL, query and all, in its message."""
    from csmarket.core.observability import _before_send

    msg = "Client error '403' for url 'https://api.example.invalid/x?key=FAKEKEY123&t=FAKETOKEN9'"
    event: Any = {"exception": {"values": [{"type": "HTTPStatusError", "value": msg}]}}
    out = _before_send(event, {})
    assert out is not None
    value = out["exception"]["values"][0]["value"]
    assert "FAKEKEY123" not in value
    assert "FAKETOKEN9" not in value
    assert "https://api.example.invalid/x" in value


def test_an_unreported_app_error_never_reaches_sentry() -> None:
    """A known upstream outage (``report = False``) is a 503 and a warning, not an error."""
    from csmarket.core.errors import UpstreamUnavailableError
    from csmarket.core.observability import _before_send
    from csmarket.modules.sales.inventory import unavailable

    quiet = unavailable()
    event: Any = {"exception": {"values": [{"type": "SalesUnavailableError"}]}}
    assert _before_send(event, {"exc_info": (type(quiet), quiet, None)}) is None
    loud = UpstreamUnavailableError("waxpeer down")
    assert _before_send(event, {"exc_info": (type(loud), loud, None)}) == event
