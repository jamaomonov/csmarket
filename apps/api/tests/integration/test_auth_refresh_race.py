"""Concurrent refresh-token rotation must not clone a session (TOCTOU guard, Review Focus 3).

``refresh_session`` reads the ``refresh_tokens`` row, checks ``revoked_at IS NULL``, then
writes ``revoked_at``. Without row locking, two requests racing with the *same* refresh
token both read it as un-revoked, both pass the check, and both mint a new session — a
stolen refresh token could be replayed alongside the legitimate use and the reuse
trip-wire would never fire.

The fix serialises concurrent refreshers on the row (``SELECT ... FOR UPDATE``): exactly
one rotates; the loser blocks on the lock, then observes the now-revoked row and trips
reuse detection, which revokes every session of the user.

The interleaving is forced deterministically: the first refresher pauses *after* it has
read the row but *before* it writes the revocation (inside ``get_user_by_id``, which the
service calls in exactly that gap), while the second refresher runs. Each refresher uses
its own session (its own connection), and the loser's session is rolled back the way the
request dependency does on a raised error.
"""

from __future__ import annotations

import asyncio

import pytest
from csmarket.core.errors import UnauthorizedError
from csmarket.modules.auth import service as auth_svc
from csmarket.modules.auth.models import RefreshToken
from csmarket.modules.users.models import User
from csmarket.modules.users.service import get_user_by_id, upsert_user_by_steam
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

pytestmark = pytest.mark.asyncio


async def _refresh(factory: async_sessionmaker[AsyncSession], token: str) -> str:
    """Run one full refresh in its own transaction; return an outcome tag."""
    async with factory() as session:
        try:
            await auth_svc.refresh_session(session, token)
        except UnauthorizedError as exc:
            await session.rollback()  # what the request dependency does on error
            return "reuse" if "reuse" in str(exc) else "rejected"
        await session.commit()
        return "ok"


async def test_concurrent_refresh_same_token_rotates_once(
    db_engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)

    async with factory() as setup:
        user = await upsert_user_by_steam(
            setup, steam_id="76561198000000042", display_name=None, avatar_url=None
        )
        tokens = await auth_svc.open_session(setup, user=user)
        await setup.commit()
        user_id = user.id

    orig_get_user = get_user_by_id
    first_in_window = asyncio.Event()
    release_first = asyncio.Event()
    state = {"paused": False}

    async def _paused_get_user(db: AsyncSession, uid: str) -> User | None:
        if not state["paused"]:
            state["paused"] = True
            first_in_window.set()
            await release_first.wait()
        return await orig_get_user(db, uid)

    monkeypatch.setattr(auth_svc, "get_user_by_id", _paused_get_user)

    async def _run_a() -> str:
        return await _refresh(factory, tokens.refresh_token)

    async def _run_b() -> str:
        await first_in_window.wait()  # start only once A is parked past its read
        task = asyncio.ensure_future(_refresh(factory, tokens.refresh_token))
        # Give B time to issue its SELECT — under the fix it blocks on A's row lock;
        # without it B sails past and commits a second rotation.
        await asyncio.sleep(0.3)
        assert not task.done(), "B must be blocked on A's row lock"
        release_first.set()
        return await task

    a_result, b_result = await asyncio.gather(_run_a(), _run_b())

    assert sorted([a_result, b_result]) == ["ok", "reuse"], [a_result, b_result]

    # The loser's trip-wire burned every session down — including the winner's
    # freshly minted one — and that survived the loser's rollback.
    async with factory() as check:
        active = (
            await check.execute(
                select(func.count())
                .select_from(RefreshToken)
                .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
            )
        ).scalar_one()
    assert active == 0
