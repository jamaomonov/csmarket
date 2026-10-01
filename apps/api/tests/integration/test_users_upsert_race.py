"""Two concurrent first sign-ins for the same Steam account must not 500.

Both callers read "not found" and both INSERT; the loser hits ``uq_users_steam_id``. The
interleaving is forced deterministically: one session's lookup is paused after it has
read "not found" but before it inserts, while a second session runs the whole upsert to
completion (insert + commit); only then is the first released to attempt its own insert.
"""

from __future__ import annotations

import asyncio

import pytest
from csmarket.modules.users import service as users_service
from csmarket.modules.users.models import User
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

pytestmark = pytest.mark.asyncio


async def test_concurrent_first_sign_in_does_not_500(
    db_engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    steam_id = "76561198000000099"

    orig_lookup = users_service.get_user_by_steam_id
    first_in_window = asyncio.Event()
    release_first = asyncio.Event()
    state = {"paused": False}

    async def _paused_lookup(db: AsyncSession, sid: str) -> User | None:
        result = await orig_lookup(db, sid)
        if sid == steam_id and not state["paused"]:
            state["paused"] = True
            first_in_window.set()
            await release_first.wait()
        return result

    monkeypatch.setattr(users_service, "get_user_by_steam_id", _paused_lookup)

    async def _run_a() -> str:
        async with factory() as session:
            user = await users_service.upsert_user_by_steam(
                session, steam_id=steam_id, display_name="Racer", avatar_url=None
            )
            await session.commit()
            return user.id

    async def _run_b() -> str:
        await first_in_window.wait()  # start only once A is parked past its read
        async with factory() as session:
            user = await users_service.upsert_user_by_steam(
                session, steam_id=steam_id, display_name="Racer", avatar_url=None
            )
            await session.commit()
        release_first.set()  # let A resume and hit the collision
        return user.id

    a_id, b_id = await asyncio.gather(_run_a(), _run_b())

    assert a_id == b_id
    async with factory() as check:
        # Global count: the table is emptied per test, so this is "how many rows exist".
        user_count = (await check.execute(select(func.count()).select_from(User))).scalar_one()
    assert user_count == 1
