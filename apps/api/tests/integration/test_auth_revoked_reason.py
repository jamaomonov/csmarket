"""Why a refresh row was revoked decides what presenting it again does.

Only a *rotated* token coming back is theft (the reuse trip-wire). A token ended by a
logout, an admin ban or an earlier trip-wire is just dead: 401, nothing else revoked. A
banned owner's revoked token is a 403 with no writes at all, so a suspended browser that
keeps asking does not touch the database.
"""

from __future__ import annotations

from datetime import datetime

import pytest
from csmarket.core.clock import now
from csmarket.core.errors import AccountSuspendedError, UnauthorizedError
from csmarket.modules.auth.models import RefreshToken
from csmarket.modules.auth.security import hash_token
from csmarket.modules.auth.service import (
    logout,
    open_session,
    refresh_session,
    revoke_all_sessions,
)
from csmarket.modules.users.service import upsert_user_by_steam
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

pytestmark = pytest.mark.asyncio


async def _user(db: AsyncSession, sid: str = "76561198000000101"):
    return await upsert_user_by_steam(db, steam_id=sid, display_name=None, avatar_url=None)


async def _reason(db: AsyncSession, refresh_token: str) -> str | None:
    row = (
        await db.execute(
            select(RefreshToken).where(RefreshToken.token_hash == hash_token(refresh_token))
        )
    ).scalar_one()
    await db.refresh(row)
    return row.revoked_reason


async def _snapshot(db: AsyncSession) -> set[tuple[str, datetime | None, str | None]]:
    rows = (
        await db.execute(
            select(RefreshToken.id, RefreshToken.revoked_at, RefreshToken.revoked_reason)
        )
    ).all()
    return {(str(r[0]), r[1], r[2]) for r in rows}


async def test_every_revocation_records_its_reason(db_session: AsyncSession) -> None:
    user = await _user(db_session)
    rotated = await open_session(db_session, user=user)
    logged_out = await open_session(db_session, user=user)
    banned = await open_session(db_session, user=user)
    await db_session.commit()

    rotated_next = await refresh_session(db_session, rotated.refresh_token)
    await logout(db_session, logged_out.refresh_token)
    await db_session.commit()
    assert await _reason(db_session, rotated.refresh_token) == "rotated"
    assert await _reason(db_session, logged_out.refresh_token) == "logout"

    await revoke_all_sessions(db_session, user.id)
    await db_session.commit()
    assert await _reason(db_session, banned.refresh_token) == "admin"
    assert await _reason(db_session, rotated_next.refresh_token) == "admin"


async def test_after_an_unban_an_old_banned_cookie_cannot_end_the_new_session(
    db_session: AsyncSession,
) -> None:
    user = await _user(db_session)
    device_b = await open_session(db_session, user=user)
    await db_session.commit()
    # Ban (every session revoked as "admin"), then unban.
    await revoke_all_sessions(db_session, user.id)
    user.banned_at = now()
    await db_session.commit()
    user.banned_at = None
    await db_session.commit()

    device_a = await open_session(db_session, user=user)  # a fresh sign-in
    await db_session.commit()
    with pytest.raises(UnauthorizedError, match="revoked"):
        await refresh_session(db_session, device_b.refresh_token)
    await db_session.commit()

    assert await refresh_session(db_session, device_a.refresh_token)


async def test_a_banned_owners_revoked_cookie_is_403_and_writes_nothing(db_engine) -> None:
    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    async with factory() as setup:
        user = await _user(setup)
        rotated = await open_session(setup, user=user)
        live = await open_session(setup, user=user)
        await setup.commit()
        await refresh_session(setup, rotated.refresh_token)  # "rotated": would trip the wire
        user.banned_at = now()  # banned, with one row deliberately left live
        await setup.commit()
    async with factory() as check:
        before = await _snapshot(check)

    async with factory() as attempt:
        with pytest.raises(AccountSuspendedError):
            await refresh_session(attempt, rotated.refresh_token)
        await attempt.rollback()  # what get_session does on the raised error

    async with factory() as check:
        assert await _snapshot(check) == before
        assert await _reason(check, live.refresh_token) is None


async def test_reusing_a_rotated_token_still_revokes_everything_as_reuse(
    db_session: AsyncSession,
) -> None:
    user = await _user(db_session)
    first = await open_session(db_session, user=user)
    other = await open_session(db_session, user=user)
    await db_session.commit()
    second = await refresh_session(db_session, first.refresh_token)
    await db_session.commit()
    with pytest.raises(UnauthorizedError, match="reuse"):
        await refresh_session(db_session, first.refresh_token)
    assert await _reason(db_session, second.refresh_token) == "reuse"
    assert await _reason(db_session, other.refresh_token) == "reuse"
    # A token the trip-wire ended is dead, not a second theft.
    with pytest.raises(UnauthorizedError, match="revoked"):
        await refresh_session(db_session, other.refresh_token)


async def test_a_legacy_revoked_row_without_a_reason_counts_as_rotated(
    db_session: AsyncSession,
) -> None:
    user = await _user(db_session)
    legacy = await open_session(db_session, user=user)
    other = await open_session(db_session, user=user)
    row = (
        await db_session.execute(
            select(RefreshToken).where(RefreshToken.token_hash == hash_token(legacy.refresh_token))
        )
    ).scalar_one()
    row.revoked_at = now()  # revoked before the column existed: reason NULL
    await db_session.commit()
    with pytest.raises(UnauthorizedError, match="reuse"):
        await refresh_session(db_session, legacy.refresh_token)
    assert await _reason(db_session, other.refresh_token) == "reuse"


async def test_a_logged_out_cookie_is_401_and_leaves_other_sessions_alone(
    db_session: AsyncSession,
) -> None:
    user = await _user(db_session)
    gone = await open_session(db_session, user=user)
    other = await open_session(db_session, user=user)
    await db_session.commit()
    await logout(db_session, gone.refresh_token)
    await db_session.commit()
    with pytest.raises(UnauthorizedError, match="revoked"):
        await refresh_session(db_session, gone.refresh_token)
    await db_session.commit()
    assert await _reason(db_session, other.refresh_token) is None
    assert await refresh_session(db_session, other.refresh_token)


async def test_the_reason_column_refuses_unknown_values(db_session: AsyncSession) -> None:
    from sqlalchemy.exc import IntegrityError

    user = await _user(db_session)
    tokens = await open_session(db_session, user=user)
    row = (
        await db_session.execute(
            select(RefreshToken).where(RefreshToken.token_hash == hash_token(tokens.refresh_token))
        )
    ).scalar_one()
    row.revoked_at = now()
    row.revoked_reason = "stolen"
    with pytest.raises(IntegrityError, match="ck_refresh_tokens_revoked_reason"):
        await db_session.commit()
    await db_session.rollback()
