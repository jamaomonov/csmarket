"""``sign_in_by_steam`` says whether this sign-in created the account (referrals attribute only
a new one, spec 2026-10-27-referrals)."""

from __future__ import annotations

import pytest
from csmarket.modules.users import service as users_svc
from csmarket.modules.users.models import User
from csmarket.modules.users.service import sign_in_by_steam
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

pytestmark = pytest.mark.asyncio

STEAM_ID = "76561198000000077"


async def test_first_sign_in_creates_then_finds(db_session: AsyncSession) -> None:
    first, created = await sign_in_by_steam(
        db_session, steam_id=STEAM_ID, display_name=None, avatar_url=None
    )
    again, created_again = await sign_in_by_steam(
        db_session, steam_id=STEAM_ID, display_name="x", avatar_url=None
    )
    assert created is True
    assert created_again is False
    assert again.id == first.id


async def test_the_loser_of_a_first_sign_in_race_did_not_create(
    db_engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    async with factory() as winner_db:
        winner, won = await sign_in_by_steam(
            winner_db, steam_id=STEAM_ID, display_name=None, avatar_url=None
        )
        await winner_db.commit()

    original = users_svc.get_user_by_steam_id
    calls = {"n": 0}

    async def _missed_once(db: AsyncSession, steam_id: str) -> User | None:
        calls["n"] += 1
        if calls["n"] == 1:  # the loser looked before the winner committed
            return None
        return await original(db, steam_id)

    monkeypatch.setattr(users_svc, "get_user_by_steam_id", _missed_once)
    async with factory() as loser_db:
        loser, created = await sign_in_by_steam(
            loser_db, steam_id=STEAM_ID, display_name=None, avatar_url=None
        )
    assert won is True
    assert created is False
    assert loser.id == winner.id
