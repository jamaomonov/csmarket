"""Steam CDN host rewrite: ByMykel links point at an Akamai host that does not
open from Uzbekistan (measured 2026-09-28); the same path serves from fastly."""

from __future__ import annotations

from csmarket.modules.skins.images import steam_image, steam_image_only

H = "https://community.akamai.steamstatic.com/economy/image/abc123"


def test_steam_hosts_are_rewritten_to_the_configured_one() -> None:
    assert steam_image(H, host="community.fastly.steamstatic.com") == (
        "https://community.fastly.steamstatic.com/economy/image/abc123"
    )
    assert (
        steam_image(
            "https://steamcommunity-a.akamaihd.net/economy/image/abc123/360fx360f",
            host="community.fastly.steamstatic.com",
        )
        == "https://community.fastly.steamstatic.com/economy/image/abc123/360fx360f"
    )


def test_other_urls_and_none_pass_through() -> None:
    assert steam_image("https://raw.githubusercontent.com/x.png", host="h") == (
        "https://raw.githubusercontent.com/x.png"
    )
    assert steam_image(None, host="h") is None
    assert steam_image("not a url", host="h") == "not a url"


def test_steam_image_only_drops_other_hosts() -> None:
    """A sticker image from a listing reaches the browser only from a Steam CDN host
    (rewritten to ours); anything else — Waxpeer's own CDN included — becomes ``None``."""
    host = "community.fastly.steamstatic.com"
    assert steam_image_only(H, host=host) == f"https://{host}/economy/image/abc123"
    assert steam_image_only("https://cdn.waxpeer.com/i/sticker.png", host=host) is None
    assert steam_image_only("https://evil.example/steamstatic.com/x.png", host=host) is None
    assert steam_image_only("https://steamstatic.com.evil.example/x.png", host=host) is None
    assert steam_image_only("not a url", host=host) is None
    assert steam_image_only("", host=host) is None
    assert steam_image_only(None, host=host) is None
