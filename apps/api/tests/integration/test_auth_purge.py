"""Expired and revoked refresh tokens must not accumulate forever.

The grace period is the point of the design: a refresh token rotates on every use, so a
row can be revoked while the client still holds the token that revoked it. Deleting at
once turns "your session was replaced" into "this session never existed".
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from csmarket.core.clock import now
from csmarket.core.ids import new_id
from csmarket.modules.auth.models import RefreshToken
from csmarket.modules.auth.service import purge_stale_refresh_tokens
from csmarket.modules.users.models import User
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def _user(db: AsyncSession) -> User:
    user = User(id=new_id(), steam_id=str(76561198000000000 + int(new_id()[:6], 16)), roles=[])
    db.add(user)
    await db.flush()
    return user


def _token(
    user_id: str, *, expires_in: timedelta, revoked_ago: timedelta | None = None
) -> RefreshToken:
    return RefreshToken(
        id=new_id(),
        user_id=user_id,
        token_hash=(new_id() + new_id()).replace("-", "")[:64],
        expires_at=now() + expires_in,
        revoked_at=(now() - revoked_ago) if revoked_ago is not None else None,
    )


async def _count(db: AsyncSession, row_id: str) -> int:
    return int(
        await db.scalar(
            select(func.count()).select_from(RefreshToken).where(RefreshToken.id == row_id)
        )
        or 0
    )


async def test_long_expired_rows_are_deleted(db_session: AsyncSession) -> None:
    user = await _user(db_session)
    db_session.add(_token(user.id, expires_in=timedelta(days=-30)))
    await db_session.flush()

    assert await purge_stale_refresh_tokens(db_session) == 1


async def test_a_live_row_survives(db_session: AsyncSession) -> None:
    user = await _user(db_session)
    keep = _token(user.id, expires_in=timedelta(days=30))
    db_session.add(keep)
    await db_session.flush()

    assert await purge_stale_refresh_tokens(db_session) == 0
    assert await _count(db_session, keep.id) == 1


async def test_a_recently_expired_row_is_kept_for_the_grace_period(
    db_session: AsyncSession,
) -> None:
    user = await _user(db_session)
    fresh_corpse = _token(user.id, expires_in=timedelta(hours=-1))
    db_session.add(fresh_corpse)
    await db_session.flush()

    assert await purge_stale_refresh_tokens(db_session) == 0
    assert await _count(db_session, fresh_corpse.id) == 1


async def test_a_long_revoked_row_is_deleted_even_if_not_yet_expired(
    db_session: AsyncSession,
) -> None:
    """A logout leaves ``expires_at`` in the future, so expiry alone never reaches it."""
    user = await _user(db_session)
    db_session.add(_token(user.id, expires_in=timedelta(days=30), revoked_ago=timedelta(days=30)))
    await db_session.flush()

    assert await purge_stale_refresh_tokens(db_session) == 1


async def test_a_recently_revoked_row_survives(db_session: AsyncSession) -> None:
    user = await _user(db_session)
    recent = _token(user.id, expires_in=timedelta(days=30), revoked_ago=timedelta(days=1))
    db_session.add(recent)
    await db_session.flush()

    assert await purge_stale_refresh_tokens(db_session) == 0
    assert await _count(db_session, recent.id) == 1


async def test_one_sweep_is_bounded(db_session: AsyncSession) -> None:
    """The first run after a long gap can meet a huge backlog; it catches up over days."""
    user = await _user(db_session)
    for _ in range(5):
        db_session.add(_token(user.id, expires_in=timedelta(days=-30)))
    await db_session.flush()

    assert await purge_stale_refresh_tokens(db_session, limit=2) == 2
