"""Sessions: open, rotate, reuse trip-wire, logout, current user, ban (Review Focus 3, 4)."""

from __future__ import annotations

from datetime import timedelta

import pytest
from csmarket.core.clock import now
from csmarket.core.errors import AccountSuspendedError, UnauthorizedError
from csmarket.core.ids import new_id
from csmarket.core.redis import get_redis
from csmarket.modules.auth.jwt import mint_access, verify
from csmarket.modules.auth.models import RefreshToken
from csmarket.modules.auth.security import hash_token
from csmarket.modules.auth.service import (
    logout,
    open_session,
    purge_stale_refresh_tokens,
    refresh_session,
    resolve_current_user,
    revoke_all_sessions,
)
from csmarket.modules.users.service import upsert_user_by_steam
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

pytestmark = pytest.mark.asyncio


async def _user(db: AsyncSession, sid: str = "76561198000000001"):
    return await upsert_user_by_steam(db, steam_id=sid, display_name=None, avatar_url=None)


async def test_open_session_yields_a_working_access_token(db_session: AsyncSession) -> None:
    user = await _user(db_session)
    tokens = await open_session(db_session, user=user)
    await db_session.commit()
    assert (await resolve_current_user(db_session, tokens.access_token)).id == user.id
    assert tokens.access_expires_in == 900


async def test_refresh_rotates_and_kills_the_old_access_token(db_session: AsyncSession) -> None:
    user = await _user(db_session)
    first = await open_session(db_session, user=user)
    await db_session.commit()
    second = await refresh_session(db_session, first.refresh_token)
    await db_session.commit()
    assert second.refresh_token != first.refresh_token
    with pytest.raises(UnauthorizedError):
        await resolve_current_user(db_session, first.access_token)
    assert (await resolve_current_user(db_session, second.access_token)).id == user.id


async def test_reusing_a_rotated_refresh_token_revokes_everything(db_session: AsyncSession) -> None:
    user = await _user(db_session)
    first = await open_session(db_session, user=user)
    other = await open_session(db_session, user=user)  # a second device
    await db_session.commit()
    second = await refresh_session(db_session, first.refresh_token)
    await db_session.commit()
    with pytest.raises(UnauthorizedError, match="reuse"):
        await refresh_session(db_session, first.refresh_token)
    await db_session.commit()
    for token in (second.refresh_token, other.refresh_token):
        with pytest.raises(UnauthorizedError):
            await refresh_session(db_session, token)


async def test_reuse_revocation_survives_the_callers_rollback(db_engine) -> None:
    """The request dependency rolls back on any raised error; the trip-wire must still hold.

    ``core.db.get_session`` rolls the request's transaction back when the handler raises,
    and a reuse is *reported* by raising. Unless the service commits the revocation itself,
    the burn-down is undone and the other devices' refresh tokens keep working.
    """
    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    async with factory() as setup:
        user = await _user(setup)
        first = await open_session(setup, user=user)
        other = await open_session(setup, user=user)
        await setup.commit()
        user_id = user.id
    async with factory() as rotate:
        second = await refresh_session(rotate, first.refresh_token)
        await rotate.commit()

    async with factory() as attacker:
        with pytest.raises(UnauthorizedError, match="reuse"):
            await refresh_session(attacker, first.refresh_token)
        await attacker.rollback()  # what get_session does on the raised error

    async with factory() as check:
        active = (
            await check.execute(
                select(func.count())
                .select_from(RefreshToken)
                .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
            )
        ).scalar_one()
        assert active == 0
        for token in (second.refresh_token, other.refresh_token):
            with pytest.raises(UnauthorizedError):
                await refresh_session(check, token)
    async with factory() as check:
        with pytest.raises(UnauthorizedError):
            await resolve_current_user(check, second.access_token)


async def test_logout_revokes_session_and_access_token(db_session: AsyncSession) -> None:
    user = await _user(db_session)
    tokens = await open_session(db_session, user=user)
    await db_session.commit()
    await logout(db_session, tokens.refresh_token, access_token=tokens.access_token)
    await db_session.commit()
    with pytest.raises(UnauthorizedError):
        await resolve_current_user(db_session, tokens.access_token)
    with pytest.raises(UnauthorizedError):
        await refresh_session(db_session, tokens.refresh_token)
    jti = verify(tokens.access_token).jti
    assert await get_redis().get(f"auth:revoked:{jti}") == "1"


async def test_cookie_only_logout_still_kills_the_access_token(db_session: AsyncSession) -> None:
    user = await _user(db_session)
    tokens = await open_session(db_session, user=user)
    await db_session.commit()
    await logout(db_session, tokens.refresh_token)
    await db_session.commit()
    with pytest.raises(UnauthorizedError, match="session revoked"):
        await resolve_current_user(db_session, tokens.access_token)


async def test_logout_with_an_unknown_token_is_a_no_op(db_session: AsyncSession) -> None:
    await logout(db_session, "never-issued")


async def test_logout_ignores_an_invalid_access_token(db_session: AsyncSession) -> None:
    await logout(db_session, "never-issued", access_token="not.a.jwt")


async def test_a_banned_account_cannot_open_or_use_a_session(db_session: AsyncSession) -> None:
    user = await _user(db_session)
    tokens = await open_session(db_session, user=user)
    user.banned_at = now()
    await db_session.commit()
    with pytest.raises(AccountSuspendedError):
        await resolve_current_user(db_session, tokens.access_token)
    with pytest.raises(AccountSuspendedError):
        await open_session(db_session, user=user)


async def test_a_banned_account_cannot_refresh(db_session: AsyncSession) -> None:
    user = await _user(db_session)
    tokens = await open_session(db_session, user=user)
    user.banned_at = now()
    await db_session.commit()
    with pytest.raises(AccountSuspendedError):
        await refresh_session(db_session, tokens.refresh_token)


async def test_an_unknown_refresh_token_is_401(db_session: AsyncSession) -> None:
    with pytest.raises(UnauthorizedError, match="invalid refresh token"):
        await refresh_session(db_session, "never-issued")


async def test_an_expired_refresh_token_is_401(db_session: AsyncSession) -> None:
    user = await _user(db_session)
    tokens = await open_session(db_session, user=user)
    row = (
        await db_session.execute(
            select(RefreshToken).where(RefreshToken.token_hash == hash_token(tokens.refresh_token))
        )
    ).scalar_one()
    row.expires_at = now() - timedelta(seconds=1)
    await db_session.commit()
    with pytest.raises(UnauthorizedError, match="expired"):
        await refresh_session(db_session, tokens.refresh_token)


async def test_only_the_hash_of_the_refresh_token_is_stored(db_session: AsyncSession) -> None:
    user = await _user(db_session)
    tokens = await open_session(db_session, user=user)
    await db_session.commit()
    hashes = (await db_session.execute(select(RefreshToken.token_hash))).scalars().all()
    assert hashes == [hash_token(tokens.refresh_token)]
    assert tokens.refresh_expires_in == 2592000
    assert verify(tokens.access_token).sid is not None


async def test_a_token_for_a_missing_user_is_401(db_session: AsyncSession) -> None:
    token = mint_access(sub=new_id(), sid=new_id())
    with pytest.raises(UnauthorizedError, match="user not found"):
        await resolve_current_user(db_session, token)


async def test_purge_drops_only_rows_past_retention(db_session: AsyncSession) -> None:
    user = await _user(db_session)
    live = await open_session(db_session, user=user)
    old_expired = await open_session(db_session, user=user)
    old_revoked = await open_session(db_session, user=user)
    recent_revoked = await open_session(db_session, user=user)
    rows = {
        r.token_hash: r for r in (await db_session.execute(select(RefreshToken))).scalars().all()
    }
    long_ago = now() - timedelta(days=8)
    rows[hash_token(old_expired.refresh_token)].expires_at = long_ago
    rows[hash_token(old_revoked.refresh_token)].revoked_at = long_ago
    rows[hash_token(recent_revoked.refresh_token)].revoked_at = now() - timedelta(days=1)
    await db_session.commit()

    assert await purge_stale_refresh_tokens(db_session, limit=1) == 1
    assert await purge_stale_refresh_tokens(db_session) == 1
    assert await purge_stale_refresh_tokens(db_session) == 0
    await db_session.commit()

    left = set((await db_session.execute(select(RefreshToken.token_hash))).scalars().all())
    assert left == {hash_token(live.refresh_token), hash_token(recent_revoked.refresh_token)}


async def test_revoke_all_sessions_ends_every_session_and_its_access_tokens(
    db_session: AsyncSession,
) -> None:
    user = await _user(db_session)
    a = await open_session(db_session, user=user)
    b = await open_session(db_session, user=user)
    bystander = await open_session(db_session, user=await _user(db_session, "76561198000000002"))
    await db_session.commit()
    assert await revoke_all_sessions(db_session, user.id) == 2
    await db_session.commit()
    for tokens in (a, b):
        with pytest.raises(UnauthorizedError, match="session revoked"):
            await resolve_current_user(db_session, tokens.access_token)
        with pytest.raises(UnauthorizedError):
            await refresh_session(db_session, tokens.refresh_token)
    assert await revoke_all_sessions(db_session, user.id) == 0
    assert (await resolve_current_user(db_session, bystander.access_token)).id != user.id


async def test_a_banned_account_with_revoked_sessions_hears_suspended_not_revoked(
    db_session: AsyncSession,
) -> None:
    user = await _user(db_session)
    tokens = await open_session(db_session, user=user)
    await db_session.commit()
    await revoke_all_sessions(db_session, user.id)
    user.banned_at = now()
    await db_session.commit()
    with pytest.raises(AccountSuspendedError):
        await resolve_current_user(db_session, tokens.access_token)
