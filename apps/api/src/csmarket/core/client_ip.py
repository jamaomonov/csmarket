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
``X-Forwarded-For``, so they resolve to the web container's socket address and
all server rendering shares one bucket. M2 must forward the visitor IP from Next
or exempt the internal network.

If the Caddyfile is ever changed to append instead of overwrite, this function
starts returning attacker-controlled data and the limiter and ``ip_guard``
become worthless -- that comment and this one are load-bearing together.
"""

from __future__ import annotations

from starlette.requests import HTTPConnection

#: Recorded when the peer cannot be determined at all (ASGI without a client,
#: e.g. some test transports). Kept as a literal rather than None so callers
#: that key caches or columns on it don't have to special-case it.
UNKNOWN_IP = "unknown"


def client_ip(request: HTTPConnection) -> str:
    """The client's address, or ``UNKNOWN_IP`` when there is no peer to read."""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        first = forwarded.split(",")[0].strip()
        if first:
            return first
    return request.client.host if request.client else UNKNOWN_IP


__all__ = ["UNKNOWN_IP", "client_ip"]
