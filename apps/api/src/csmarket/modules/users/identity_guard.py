"""Length guards for the Steam profile fields copied onto a :class:`User`.

Third-party profile fields are guarded before they reach an INSERT: a URL over the limit
is dropped, a name is truncated to the column width.
"""

from __future__ import annotations

from sqlalchemy import String

from csmarket.modules.users.models import User

#: Generous headroom over any real avatar URL, while refusing something pathological (a
#: multi-KB payload, a corrupted value) before it reaches Postgres. Independent of the
#: column width — the column is ``text``, so a value this function accepts never fails
#: the INSERT/UPDATE on its own.
MAX_AVATAR_URL_LENGTH = 2048

#: ``users.display_name``'s own column width, read off the model rather than hand-copied
#: so a changed column changes this guard with it. A name has no "broken" state the way a
#: truncated URL does, so this guard truncates instead of dropping.
_display_name_type = User.__table__.c.display_name.type
assert isinstance(_display_name_type, String), "users.display_name must stay a String column"
assert _display_name_type.length is not None, "users.display_name must stay length-bounded"
MAX_DISPLAY_NAME_LENGTH: int = _display_name_type.length


def safe_avatar_url(url: str | None) -> str | None:
    """Return ``url`` stripped, or ``None`` if absent, blank or absurdly long.

    A truncated URL is not a smaller picture — it is a broken link — so "too long" is
    treated exactly like "not supplied": no avatar, never a corrupted one.

    Args:
        url: The candidate avatar URL from a Steam profile.

    Returns:
        The stripped URL, or ``None`` when there is nothing safe to store.
    """
    if url is None:
        return None
    stripped = url.strip()
    if not stripped or len(stripped) > MAX_AVATAR_URL_LENGTH:
        return None
    return stripped


def safe_display_name(name: str | None) -> str | None:
    """Return ``name`` stripped (and truncated to fit), or ``None`` if blank.

    Unlike a URL, a shortened name is still a usable name, so it is truncated rather
    than dropped.

    Args:
        name: The candidate display name from a Steam profile.

    Returns:
        The stripped, possibly truncated name, or ``None`` when blank.
    """
    if name is None:
        return None
    stripped = name.strip()
    if not stripped:
        return None
    return stripped[:MAX_DISPLAY_NAME_LENGTH]


__all__ = [
    "MAX_AVATAR_URL_LENGTH",
    "MAX_DISPLAY_NAME_LENGTH",
    "safe_avatar_url",
    "safe_display_name",
]
