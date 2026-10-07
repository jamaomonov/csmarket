"""Steam CDN URLs served from a host our customers can reach.

ByMykel (and Waxpeer's stickers) link images on
``community.akamai.steamstatic.com``, which did not open from Uzbekistan on
2026-09-28 while ``community.fastly.steamstatic.com`` served the identical file
by the same ``/economy/image/<hash>`` path. The host is a setting
(``cs2_skins_image_host``) so it can be switched without a data migration —
rows keep whatever URL the import wrote; the rewrite happens on the way out.

Sticker and charm icons by their game path (``/apps/730/icons/econ/…``, as LIS-SKINS and
some inspect-link stickers name them) are served by ``cdn.*`` only — ``community.*``
redirects them to the Steam home page (checked 2026-10-07) — so they go to the ``cdn.``
twin of the configured host.
"""

from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit

_STEAM_HOST_SUFFIXES = (".steamstatic.com", ".akamaihd.net")
_ICON_PATH = "/apps/"


def _icon_host(host: str) -> str:
    """``community.fastly.steamstatic.com`` → ``cdn.fastly.steamstatic.com``."""
    return "cdn." + host.removeprefix("community.") if host.startswith("community.") else host


def steam_image(url: str | None, *, host: str) -> str | None:
    """``url`` with a Steam CDN host replaced by ``host``; anything else unchanged."""
    if not url:
        return url
    parts = urlsplit(url)
    if not parts.hostname or not parts.hostname.endswith(_STEAM_HOST_SUFFIXES):
        return url
    if parts.path.startswith(_ICON_PATH):
        host = _icon_host(host)
    return urlunsplit((parts.scheme, host, parts.path, parts.query, parts.fragment))


def steam_image_only(url: str | None, *, host: str) -> str | None:
    """Like :func:`steam_image`, but a URL on any other host becomes ``None``.

    For images that come from Waxpeer (listing stickers): only a Steam CDN image may
    reach a browser, never one on Waxpeer's own CDN or anywhere else.
    """
    if not url:
        return None
    hostname = urlsplit(url).hostname
    if not hostname or not hostname.endswith(_STEAM_HOST_SUFFIXES):
        return None
    return steam_image(url, host=host)


__all__ = ["steam_image", "steam_image_only"]
