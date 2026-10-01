"""Refresh-token cookie helpers for the auth HTTP surface.

The refresh token is delivered as an ``HttpOnly`` cookie (ruling P2) instead of the JSON
body, so an XSS regression cannot read a 30-day session. Attributes are
environment-aware:

- ``Secure`` and ``Domain`` are only set in production. Dev and the test suite run over
  plain ``http``/``localhost`` where a ``Secure`` cookie would be dropped by the browser
  and a ``Domain`` attribute for a bare hostname is invalid.
- ``SameSite=Lax`` + ``Path=/`` always. ``csmarket.uz`` and its ``api.``/``admin.``
  subdomains share the registrable domain, so the cookie is first-party (same-site) on
  the cross-subdomain XHR the refresh flow makes to ``api.csmarket.uz``.

One cookie serves the storefront and the admin (ruling P8): signing out of one signs out
of the other.
"""

from __future__ import annotations

from urllib.parse import urlsplit

from fastapi import Response

from csmarket.core.config import Settings

REFRESH_COOKIE_NAME = "csmarket_refresh"


def _cookie_domain(settings: Settings) -> str | None:
    """Return the parent domain for the cookie, or ``None`` to keep it host-only.

    Host-only (dev/test/localhost) scopes the cookie to the API host, which is all the
    refresh flow needs. In production it widens to the registrable parent
    (``.csmarket.uz``) derived from ``web_base_url`` so the cookie is first-party to the
    storefront and the admin.
    """
    if not settings.is_prod:
        return None
    host = urlsplit(settings.web_base_url or settings.base_url).hostname
    if not host:
        return None
    labels = host.split(".")
    if len(labels) < 2:
        return None
    return "." + ".".join(labels[-2:])


def set_refresh_cookie(response: Response, *, token: str, max_age: int, settings: Settings) -> None:
    """Attach the rotating refresh cookie to ``response``."""
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=token,
        max_age=max_age,
        path="/",
        httponly=True,
        secure=settings.is_prod,
        samesite="lax",
        domain=_cookie_domain(settings),
    )


def clear_refresh_cookie(response: Response, *, settings: Settings) -> None:
    """Expire the refresh cookie (logout). Attributes must match the set call."""
    response.delete_cookie(
        key=REFRESH_COOKIE_NAME,
        path="/",
        httponly=True,
        secure=settings.is_prod,
        samesite="lax",
        domain=_cookie_domain(settings),
    )


cookie_domain = _cookie_domain

__all__ = [
    "REFRESH_COOKIE_NAME",
    "clear_refresh_cookie",
    "cookie_domain",
    "set_refresh_cookie",
]
