"""Unit tests for :mod:`csmarket.modules.users.identity_guard`.

Third-party profile fields (Steam persona name and avatar) are guarded before they reach
an INSERT: a URL over the limit is dropped, a name is truncated to the column width.
"""

from __future__ import annotations

from csmarket.modules.users.identity_guard import (
    MAX_AVATAR_URL_LENGTH,
    MAX_DISPLAY_NAME_LENGTH,
    safe_avatar_url,
    safe_display_name,
)


def test_safe_avatar_url_passes_through_a_normal_url() -> None:
    url = "https://avatars.steamstatic.com/abc123_full.jpg"
    assert safe_avatar_url(url) == url


def test_safe_avatar_url_none_stays_none() -> None:
    assert safe_avatar_url(None) is None


def test_safe_avatar_url_blank_becomes_none() -> None:
    assert safe_avatar_url("   ") is None


def test_safe_avatar_url_strips_surrounding_whitespace() -> None:
    assert safe_avatar_url("  https://example.test/a.png  ") == "https://example.test/a.png"


def test_safe_avatar_url_drops_an_absurdly_long_url() -> None:
    """A truncated URL is a broken link, so an over-long one is dropped, not shortened."""
    absurd = "https://avatars.steamstatic.com/" + ("a" * 3000)
    assert safe_avatar_url(absurd) is None


def test_safe_avatar_url_accepts_up_to_the_configured_limit() -> None:
    prefix = "https://example.test/"
    just_fits = prefix + ("a" * (MAX_AVATAR_URL_LENGTH - len(prefix)))
    assert len(just_fits) == MAX_AVATAR_URL_LENGTH
    assert safe_avatar_url(just_fits) == just_fits
    assert safe_avatar_url(just_fits + "a") is None


def test_safe_display_name_passes_through_a_normal_name() -> None:
    assert safe_display_name("Buyer Person") == "Buyer Person"


def test_safe_display_name_none_stays_none() -> None:
    assert safe_display_name(None) is None


def test_safe_display_name_blank_becomes_none() -> None:
    assert safe_display_name("   ") is None


def test_safe_display_name_truncates_an_over_length_name() -> None:
    """A shortened name is still a usable name, so it is truncated, not dropped."""
    long_name = "A" * (MAX_DISPLAY_NAME_LENGTH + 50)
    result = safe_display_name(long_name)
    assert result is not None
    assert len(result) == MAX_DISPLAY_NAME_LENGTH
    assert result == "A" * MAX_DISPLAY_NAME_LENGTH
