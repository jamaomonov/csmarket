"""Resolve the calling client's IP address.

Two consumers depend on getting the same answer: the global rate limiter
(``bootstrap``) and the auth brute-force guard (``auth.ip_guard``). Each used
to carry its own copy of this parsing in the project this one was ported from;
divergence between them would be silent and would matter, because a limiter
keyed on one value while a guard keys on another is a liability, not a
safeguard.

Why the FIRST entry of ``X-Forwarded-For`` can be trusted:

The stack's own Caddy is the only hop in front of this app
(``infra/caddy/Caddyfile.prod``). It *overwrites* ``X-Forwarded-For`` with
exactly one value: ``{client_ip}``, which Caddy resolves from
``Cf-Connecting-Ip`` when -- and only when -- the peer is in Cloudflare's
published ranges (``trusted_proxies`` + ``client_ip_headers`` in the global
block), and from the socket peer otherwise. So a caller cannot inject a chain
and pick an address, and nothing from outside the box reaches FastAPI around
that proxy (the api port is not published).

One caller inside the compose network does: the storefront's server-side
requests go straight to ``http://api:8000`` (``API_INTERNAL_URL``) with no
``X-Forwarded-For``. Left alone they resolve to the web container's socket
address and all server rendering shares one bucket (SEC-01). So the storefront
names the visitor itself, in ``X-Storefront-Client-Ip``, next to the shared
secret ``X-Storefront-Secret`` (``CSMARKET_STOREFRONT_SECRET`` on both sides).
That header is trusted only when all of these hold:

* a secret is configured and the request's matches it (constant-time compare);
* the request carries no ``X-Forwarded-For`` -- our Caddy sets it on every
  request from the internet, the storefront never does, so its absence means
  the call did not come through the public edge;
* the value parses as an IP address.

Anything else is today's behaviour, header ignored. Caddy also strips both
headers on the way in (``(upstream)`` in the Caddyfile), belt and braces.

If the Caddyfile is ever changed to append instead of overwrite, this function
starts returning attacker-controlled data and the limiter and ``ip_guard``
become worthless -- that comment and this one are load-bearing together.
"""

from __future__ import annotations

import hmac
import ipaddress

from starlette.requests import HTTPConnection

from csmarket.core.config import get_settings

#: Recorded when the peer cannot be determined at all (ASGI without a client,
#: e.g. some test transports). Kept as a literal rather than None so callers
#: that key caches or columns on it don't have to special-case it.
UNKNOWN_IP = "unknown"

#: The storefront's shared secret on its server-side calls (ADR-0003).
STOREFRONT_SECRET_HEADER = "X-Storefront-Secret"  # noqa: S105 -- a header name, not a secret
#: The visitor the storefront is rendering for, trusted only beside the secret.
STOREFRONT_CLIENT_IP_HEADER = "X-Storefront-Client-Ip"


def _storefront_visitor(request: HTTPConnection) -> str | None:
    """The visitor IP the storefront vouches for, or ``None`` when it cannot be trusted."""
    if "X-Forwarded-For" in request.headers:
        return None  # came through Caddy, i.e. from the internet
    expected = get_settings().storefront_secret
    given = request.headers.get(STOREFRONT_SECRET_HEADER)
    if not expected or given is None:
        return None
    if not hmac.compare_digest(given.encode(), expected.encode()):
        return None
    raw = request.headers.get(STOREFRONT_CLIENT_IP_HEADER, "").strip()
    try:
        return str(ipaddress.ip_address(raw))
    except ValueError:
        return None


def client_ip(request: HTTPConnection) -> str:
    """The client's address, or ``UNKNOWN_IP`` when there is no peer to read."""
    visitor = _storefront_visitor(request)
    if visitor is not None:
        return visitor
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        first = forwarded.split(",")[0].strip()
        if first:
            return first
    return request.client.host if request.client else UNKNOWN_IP


__all__ = [
    "STOREFRONT_CLIENT_IP_HEADER",
    "STOREFRONT_SECRET_HEADER",
    "UNKNOWN_IP",
    "client_ip",
]
