"""The partner webhook URL guard: shape and public-address checks (plan C, Task 1)."""

from __future__ import annotations

import asyncio
import socket
from typing import Any

import pytest
from csmarket.core.errors import ValidationError
from csmarket.modules.public_api import webhook_url
from csmarket.modules.public_api.webhook_url import check_url, public_addresses


def test_check_url_accepts_https() -> None:
    assert check_url("https://hooks.example.com/csm") == "https://hooks.example.com/csm"
    assert check_url("  https://hooks.example.com:8443/a?b=1 ") == (
        "https://hooks.example.com:8443/a?b=1"
    )


def test_check_url_normalises_the_host() -> None:
    assert check_url("https://Hooks.EXAMPLE.com:8443/A") == "https://hooks.example.com:8443/A"
    assert check_url("https://bücher.example/x") == "https://xn--bcher-kva.example/x"


@pytest.mark.parametrize(
    "url",
    [
        "http://hooks.example.com/csm",
        "https://u:p@hooks.example.com/csm",
        "https://hooks.example.com/csm#x",
        "https://hooks.example.com/" + "a" * 600,
        "https:///nohost",
        "ftp://hooks.example.com",
        "https://hooks.example.com:99999/x",
        "",
        "https://a..b/x",
        "https://" + "a" * 64 + ".com/x",
        "https://hooks.exa\tmple.com/x",
        "https://hooks.example.com/a\nb",
        "https://hooks.example.com/a b",
        "https://hooks.example.com/\x7f",
    ],
)
def test_check_url_refuses(url: str) -> None:
    with pytest.raises(ValidationError) as exc:
        check_url(url)
    assert exc.value.extra["code"] == "webhook_url_invalid"


def _resolver(monkeypatch: pytest.MonkeyPatch, *addrs: str) -> None:
    async def fake(self: Any, host: str, port: int, **kw: Any) -> list[Any]:
        return [
            (
                socket.AF_INET6 if ":" in a else socket.AF_INET,
                socket.SOCK_STREAM,
                6,
                "",
                (a, port),
            )
            for a in addrs
        ]

    monkeypatch.setattr(asyncio.BaseEventLoop, "getaddrinfo", fake)


@pytest.mark.parametrize(
    "bad",
    [
        "10.0.0.1",
        "127.0.0.1",
        "169.254.169.254",
        "::1",
        "::ffff:10.0.0.1",
        "100.64.1.1",
        "0.0.0.0",
        "224.0.0.1",
        "240.0.0.1",
        "192.168.1.1",
        "64:ff9b::a00:1",
        "2002:a00:1::1",
        "::a00:1",
        "fe80::1%eth0",
        "::",
        "198.18.0.1",
        "2001:0:4136:e378:8000:63bf:3fff:fdd2",
    ],
)
async def test_refuses_non_public(monkeypatch: pytest.MonkeyPatch, bad: str) -> None:
    _resolver(monkeypatch, bad)
    with pytest.raises(ValidationError) as exc:
        await public_addresses("h.example.com", 443)
    assert exc.value.extra["code"] == "webhook_url_private"


async def test_refuses_a_mix(monkeypatch: pytest.MonkeyPatch) -> None:
    _resolver(monkeypatch, "93.184.216.34", "10.0.0.1")
    with pytest.raises(ValidationError):
        await public_addresses("h.example.com", 443)


async def test_accepts_public(monkeypatch: pytest.MonkeyPatch) -> None:
    _resolver(monkeypatch, "93.184.216.34")
    assert await public_addresses("h.example.com", 443) == ["93.184.216.34"]


async def test_unresolvable_is_private(monkeypatch: pytest.MonkeyPatch) -> None:
    async def boom(self: Any, host: str, port: int, **kw: Any) -> list[Any]:
        raise socket.gaierror("nope")

    monkeypatch.setattr(asyncio.BaseEventLoop, "getaddrinfo", boom)
    with pytest.raises(ValidationError) as exc:
        await public_addresses("h.example.com", 443)
    assert exc.value.extra["code"] == "webhook_url_private"


async def test_empty_resolution_is_private(monkeypatch: pytest.MonkeyPatch) -> None:
    _resolver(monkeypatch)
    with pytest.raises(ValidationError):
        await public_addresses("h.example.com", 443)


@pytest.mark.parametrize("host", ["2130706433", "0x7f.1", "a..b", "a" * 64 + ".com"])
async def test_odd_hosts_are_refused_not_crashed(
    monkeypatch: pytest.MonkeyPatch, host: str
) -> None:
    _resolver(monkeypatch, "127.0.0.1")
    with pytest.raises(ValidationError) as exc:
        await public_addresses(host, 443)
    assert exc.value.extra["code"] == "webhook_url_private"


async def test_unicode_error_from_the_resolver_is_private(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def boom(self: Any, host: str, port: int, **kw: Any) -> list[Any]:
        raise UnicodeError("label empty")

    monkeypatch.setattr(asyncio.BaseEventLoop, "getaddrinfo", boom)
    with pytest.raises(ValidationError) as exc:
        await public_addresses("a..b", 443)
    assert exc.value.extra["code"] == "webhook_url_private"


async def test_slow_lookup_times_out(monkeypatch: pytest.MonkeyPatch) -> None:
    async def slow(self: Any, host: str, port: int, **kw: Any) -> list[Any]:
        await asyncio.sleep(5)
        return []

    monkeypatch.setattr(asyncio.BaseEventLoop, "getaddrinfo", slow)
    monkeypatch.setattr(webhook_url, "RESOLVE_TIMEOUT_SECONDS", 0.05)
    with pytest.raises(ValidationError) as exc:
        await public_addresses("h.example.com", 443)
    assert exc.value.extra["code"] == "webhook_url_private"
