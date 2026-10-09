"""The partner webhook URL guard: its shape, and that it resolves to public addresses only.

``check_url`` is pure; ``public_addresses`` resolves the host and refuses the URL if *any*
address is private, loopback, link-local, multicast, reserved, unspecified or CGNAT. It runs
when the URL is saved and again before every send (DNS may change in between). The URL is
never logged -- callers log the host at most.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from urllib.parse import urlsplit, urlunsplit

from csmarket.core.errors import ValidationError

MAX_URL_LENGTH = 500
#: Refused on top of the stdlib flags (``is_global`` already covers most of these).
_V4_REFUSED = tuple(ipaddress.ip_network(n) for n in ("100.64.0.0/10", "198.18.0.0/15"))
_NAT64 = ipaddress.ip_network("64:ff9b::/96")
_V6_REFUSED = tuple(ipaddress.ip_network(n) for n in ("::/96", "2001::/32"))
#: Seconds a host lookup may take, saving and sending alike.
RESOLVE_TIMEOUT_SECONDS = 3.0


def _invalid(message: str) -> ValidationError:
    return ValidationError(message, code="webhook_url_invalid")


def check_url(url: str) -> str:
    """Return the normalised URL, or raise ``ValidationError(webhook_url_invalid)``.

    ``https`` only, a host, no userinfo, no fragment, no whitespace or control character,
    at most 500 characters. The result has a lowercased, IDNA-encoded host: it is exactly
    what is checked, stored and later connected to.
    """
    url = url.strip()
    if not url or len(url) > MAX_URL_LENGTH:
        raise _invalid("the webhook URL must be 1 to 500 characters")
    if any(ord(ch) <= 0x20 or ord(ch) == 0x7F for ch in url):
        raise _invalid("the webhook URL must not contain whitespace or control characters")
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError as exc:
        raise _invalid("the webhook URL is malformed") from exc
    if parts.scheme != "https":
        raise _invalid("the webhook URL must use https")
    host = parts.hostname
    if not host:
        raise _invalid("the webhook URL needs a host")
    if parts.username is not None or parts.password is not None or "@" in parts.netloc:
        raise _invalid("the webhook URL must not carry credentials")
    if parts.fragment or "#" in url:
        raise _invalid("the webhook URL must not have a fragment")
    if port is not None and port == 0:
        raise _invalid("the webhook URL port is invalid")
    try:
        ascii_host = host.encode("idna").decode("ascii").lower()
    except UnicodeError as exc:
        raise _invalid("the webhook URL host is invalid") from exc
    if len(ascii_host) > 253:
        raise _invalid("the webhook URL host is invalid")
    netloc = f"[{ascii_host}]" if ":" in ascii_host else ascii_host
    if port is not None:
        netloc += f":{port}"
    return urlunsplit(("https", netloc, parts.path, parts.query, ""))


def _embedded_v4(ip: ipaddress.IPv6Address) -> ipaddress.IPv4Address | None:
    """The IPv4 address an IPv4-mapped, NAT64 or 6to4 address carries, else ``None``."""
    if ip.ipv4_mapped is not None:
        return ip.ipv4_mapped
    if ip in _NAT64:
        return ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF)
    return ip.sixtofour


def is_public(address: str) -> bool:
    """Whether ``address`` is a globally routable IP.

    IPv4-mapped, NAT64 (``64:ff9b::/96``) and 6to4 (``2002::/16``) addresses are judged by the
    IPv4 address they embed; IPv4-compatible (``::/96``) and Teredo are refused outright.
    """
    try:
        ip = ipaddress.ip_address(address.split("%", 1)[0])
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address):
        embedded = _embedded_v4(ip)
        if embedded is not None:
            return is_public(str(embedded))
        refused = any(ip in n for n in _V6_REFUSED)
    else:
        refused = any(ip in n for n in _V4_REFUSED)
    if isinstance(ip, ipaddress.IPv6Address) and ip.is_site_local:  # fec0::/10, deprecated
        return False
    flagged = (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )
    return not (refused or flagged or not ip.is_global)


async def public_addresses(host: str, port: int) -> list[str]:
    """Resolve ``host`` (3 s at most) and return its addresses; refuse unless all are public.

    The one bounded resolver: the save route and the sender both use it.

    Raises:
        ValidationError: ``webhook_url_private`` when nothing resolves or any address is not
            public.
    """
    private = ValidationError(
        "the webhook host must resolve to public addresses only", code="webhook_url_private"
    )
    try:
        infos = await asyncio.wait_for(
            asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM),
            timeout=RESOLVE_TIMEOUT_SECONDS,
        )
    except (OSError, UnicodeError, ValueError, TimeoutError) as exc:
        raise private from exc
    addresses = sorted({str(info[4][0]) for info in infos})
    if not addresses or not all(is_public(a) for a in addresses):
        raise private
    return addresses


__all__ = [
    "MAX_URL_LENGTH",
    "RESOLVE_TIMEOUT_SECONDS",
    "check_url",
    "is_public",
    "public_addresses",
]
