"""The address every guard keys on."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from csmarket.core.client_ip import (
    STOREFRONT_CLIENT_IP_HEADER,
    STOREFRONT_SECRET_HEADER,
    UNKNOWN_IP,
    client_ip,
)
from csmarket.core.config import Settings, get_settings
from pydantic import ValidationError
from starlette.datastructures import Headers


class _Req:
    """Stand-in for the two attributes ``client_ip`` reads.

    Uses Starlette's own ``Headers`` rather than a dict so the case-insensitive
    lookup under test is the real one — a dict here would make the test pass or
    fail on the stub's behaviour instead of the app's.
    """

    def __init__(self, headers: dict[str, str], peer: str | None) -> None:
        self.headers = Headers(headers)
        self.client = type("C", (), {"host": peer})() if peer else None


def _req(headers: dict[str, str] | None = None, peer: str | None = None) -> Any:
    return _Req(headers or {}, peer)


def test_takes_the_first_forwarded_entry() -> None:
    # Our Caddy overwrites the header with exactly one value, the visitor
    # (core/client_ip.py). Should a chain ever arrive anyway, the leftmost entry
    # is the one taken — never the last.
    assert (
        client_ip(_req({"X-Forwarded-For": "203.0.113.7, 10.0.0.2"}, "10.0.0.2")) == "203.0.113.7"
    )


def test_header_lookup_is_case_insensitive() -> None:
    # Starlette headers are case-insensitive; asserting it so a refactor to
    # plain dicts cannot silently start missing the header in production.
    assert client_ip(_req({"x-forwarded-for": "198.51.100.4"}, "10.0.0.2")) == "198.51.100.4"


def test_falls_back_to_the_socket_peer() -> None:
    assert client_ip(_req({}, "192.0.2.9")) == "192.0.2.9"


def test_empty_header_does_not_shadow_the_peer() -> None:
    # A blank or comma-only header would otherwise yield "", which downstream
    # would happily store as an address and key a rate-limit bucket on.
    assert client_ip(_req({"X-Forwarded-For": "   "}, "192.0.2.9")) == "192.0.2.9"
    assert client_ip(_req({"X-Forwarded-For": ","}, "192.0.2.9")) == "192.0.2.9"


def test_reports_unknown_when_there_is_no_peer_at_all() -> None:
    assert client_ip(_req({}, None)) == UNKNOWN_IP


# --- the storefront's server-side calls (SEC-01, ADR-0003 "Storefront visitor IP") ---

_SECRET = "s" * 40
_VISITOR = "198.51.100.23"
_WEB_PEER = "172.18.0.9"


@pytest.fixture
def storefront_secret(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("CSMARKET_STOREFRONT_SECRET", _SECRET)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def no_storefront_secret(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.delenv("CSMARKET_STOREFRONT_SECRET", raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _ssr(secret: str | None = _SECRET, ip: str | None = _VISITOR, **extra: str) -> Any:
    headers: dict[str, str] = dict(extra)
    if secret is not None:
        headers[STOREFRONT_SECRET_HEADER] = secret
    if ip is not None:
        headers[STOREFRONT_CLIENT_IP_HEADER] = ip
    return _req(headers, _WEB_PEER)


@pytest.mark.usefixtures("storefront_secret")
def test_storefront_call_with_the_secret_is_keyed_on_the_visitor() -> None:
    assert client_ip(_ssr()) == _VISITOR


@pytest.mark.usefixtures("storefront_secret")
def test_storefront_ipv6_visitor_is_accepted() -> None:
    assert client_ip(_ssr(ip=" 2001:db8::7 ")) == "2001:db8::7"


@pytest.mark.usefixtures("storefront_secret")
def test_wrong_secret_falls_back_to_the_peer() -> None:
    assert client_ip(_ssr(secret="x" * 40)) == _WEB_PEER


@pytest.mark.usefixtures("storefront_secret")
def test_missing_secret_falls_back_to_the_peer() -> None:
    assert client_ip(_ssr(secret=None)) == _WEB_PEER


@pytest.mark.usefixtures("storefront_secret")
def test_missing_or_junk_visitor_ip_falls_back_to_the_peer() -> None:
    # A junk value must never become a rate-limit key of the caller's choosing.
    assert client_ip(_ssr(ip=None)) == _WEB_PEER
    assert client_ip(_ssr(ip="not-an-ip")) == _WEB_PEER
    assert client_ip(_ssr(ip="")) == _WEB_PEER


@pytest.mark.usefixtures("storefront_secret")
def test_visitor_header_through_caddy_is_ignored_even_with_the_right_secret() -> None:
    # Everything from the internet passes our Caddy, which always sets X-Forwarded-For;
    # the storefront calls api:8000 directly and never sends it. A request carrying
    # X-Forwarded-For came from outside, and the visitor header is never trusted on it.
    req = _ssr(**{"X-Forwarded-For": "203.0.113.50"})
    assert client_ip(req) == "203.0.113.50"


@pytest.mark.usefixtures("no_storefront_secret")
def test_forged_headers_are_ignored_while_the_feature_is_off() -> None:
    # No secret configured: an empty header value must not "match" an empty setting.
    assert client_ip(_ssr(secret="")) == _WEB_PEER
    assert client_ip(_ssr()) == _WEB_PEER


def test_short_storefront_secret_is_refused() -> None:
    with pytest.raises(ValidationError):
        Settings(storefront_secret="short")
