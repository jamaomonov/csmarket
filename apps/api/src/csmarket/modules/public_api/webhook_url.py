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
from urllib.parse import urlsplit

from csmarket.core.errors import ValidationError

MAX_URL_LENGTH = 500
_CGNAT = ipaddress.ip_network("100.64.0.0/10")


def _invalid(message: str) -> ValidationError:
    return ValidationError(message, code="webhook_url_invalid")


def check_url(url: str) -> str:
    """Return the normalised URL, or raise ``ValidationError(webhook_url_invalid)``.

    ``https`` only, a host, no userinfo, no fragment, at most 500 characters.
    """
    url = url.strip()
    if not url or len(url) > MAX_URL_LENGTH:
        raise _invalid("the webhook URL must be 1 to 500 characters")
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError as exc:
        raise _invalid("the webhook URL is malformed") from exc
    if parts.scheme != "https":
        raise _invalid("the webhook URL must use https")
    if not parts.hostname:
        raise _invalid("the webhook URL needs a host")
    if parts.username is not None or parts.password is not None or "@" in parts.netloc:
        raise _invalid("the webhook URL must not carry credentials")
    if parts.fragment or "#" in url:
        raise _invalid("the webhook URL must not have a fragment")
    if port is not None and port == 0:
        raise _invalid("the webhook URL port is invalid")
    return url


def is_public(address: str) -> bool:
    """Whether ``address`` is a globally routable IP (IPv4-mapped IPv6 is unwrapped first)."""
    try:
        ip = ipaddress.ip_address(address.split("%", 1)[0])
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    if (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    ):
        return False
    return not (isinstance(ip, ipaddress.IPv4Address) and ip in _CGNAT)


async def public_addresses(host: str, port: int) -> list[str]:
    """Resolve ``host`` and return its addresses; refuse unless every one is public.

    Raises:
        ValidationError: ``webhook_url_private`` when nothing resolves or any address is not
            public.
    """
    private = ValidationError(
        "the webhook host must resolve to public addresses only", code="webhook_url_private"
    )
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise private from exc
    addresses = sorted({str(info[4][0]) for info in infos})
    if not addresses or not all(is_public(a) for a in addresses):
        raise private
    return addresses


__all__ = ["MAX_URL_LENGTH", "check_url", "is_public", "public_addresses"]
