"""Users: Steam upsert, look-ups, roles, profile, trade link. Flushes, never commits."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.clock import now
from csmarket.core.ids import new_id
from csmarket.modules.users.identity_guard import safe_avatar_url, safe_display_name
from csmarket.modules.users.models import User

#: steamid64 = 32-bit account id (a trade link's ``partner``) + this.
STEAM64_BASE = 76561197960265728


async def get_user_by_id(db: AsyncSession, user_id: str) -> User | None:
    """The user with ``user_id``, or ``None``."""
    return await db.get(User, user_id)


async def get_user_by_steam_id(db: AsyncSession, steam_id: str) -> User | None:
    """The user owning ``steam_id``, or ``None``."""
    return (await db.execute(select(User).where(User.steam_id == steam_id))).scalar_one_or_none()


def _refresh_profile(user: User, *, display_name: str | None, avatar_url: str | None) -> None:
    """Overwrite profile fields only with values Steam actually gave us this time."""
    if display_name is not None:
        user.display_name = display_name
    if avatar_url is not None:
        user.avatar_url = avatar_url
    user.updated_at = now()


async def upsert_user_by_steam(
    db: AsyncSession,
    *,
    steam_id: str,
    display_name: str | None,
    avatar_url: str | None,
) -> User:
    """Find-or-create the account for a verified steamid64.

    Two concurrent first sign-ins for one account both see "not found"; the loser's
    INSERT hits ``uq_users_steam_id`` inside a SAVEPOINT, re-reads the winner's row and
    continues as an existing account instead of 500ing.

    Args:
        db: The request's session; flushed, never committed here.
        steam_id: The verified steamid64, as text.
        display_name: Steam persona name, if Steam gave one.
        avatar_url: Steam avatar URL, if Steam gave one.

    Returns:
        The existing or newly created user.
    """
    name = safe_display_name(display_name)
    avatar = safe_avatar_url(avatar_url)
    existing = await get_user_by_steam_id(db, steam_id)
    if existing is not None:
        _refresh_profile(existing, display_name=name, avatar_url=avatar)
        await db.flush()
        return existing
    user = User(
        id=new_id(), steam_id=steam_id, display_name=name, avatar_url=avatar, locale="ru", roles=[]
    )
    try:
        async with db.begin_nested():
            db.add(user)
            await db.flush()
    except IntegrityError:
        winner = await get_user_by_steam_id(db, steam_id)
        if winner is None:  # pragma: no cover - the constraint that fired guarantees a row
            raise
        _refresh_profile(winner, display_name=name, avatar_url=avatar)
        await db.flush()
        return winner
    return user


async def set_roles(db: AsyncSession, user: User, roles: list[str]) -> None:
    """Replace ``user.roles`` (sorted, de-duplicated)."""
    user.roles = sorted(set(roles))
    user.updated_at = now()
    await db.flush()


async def update_profile(db: AsyncSession, user: User, *, fields: dict[str, object]) -> None:
    """Apply ``MePatchIn.model_dump(exclude_unset=True)``.

    Setting an email resets verification (ruling P4: verification arrives in M4).
    """
    if "locale" in fields and fields["locale"] is not None:
        user.locale = str(fields["locale"])
    if "email" in fields:
        new = fields["email"]
        if new != user.email:
            user.email = None if new is None else str(new)
            user.email_verified_at = None
    user.updated_at = now()
    await db.flush()


async def save_trade_link(db: AsyncSession, user: User, url: str) -> None:
    """Store a parsed, owned link; a new link forgets the previous check."""
    if url != user.trade_link:
        user.trade_link = url
        user.trade_link_verdict = None
        user.trade_link_reason = None
        user.trade_link_checked_at = None
    user.updated_at = now()
    await db.flush()


async def record_trade_link_check(
    db: AsyncSession, user: User, *, verdict: str | None, reason: str | None
) -> None:
    """Persist a check. ``unavailable`` (no verdict) leaves ``trade_link_checked_at`` alone."""
    user.trade_link_verdict = verdict
    user.trade_link_reason = reason
    if verdict is not None:
        user.trade_link_checked_at = now()
    user.updated_at = now()
    await db.flush()
