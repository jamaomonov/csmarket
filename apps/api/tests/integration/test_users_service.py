"""Steam upsert: one account per steamid64, profile refreshed on every sign-in."""

from __future__ import annotations

import pytest
from csmarket.modules.users.models import User
from csmarket.modules.users.service import (
    get_user_by_steam_id,
    set_roles,
    upsert_user_by_steam,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio

SID = "76561198000000001"


async def test_first_sign_in_creates_the_account(db_session: AsyncSession) -> None:
    user = await upsert_user_by_steam(
        db_session, steam_id=SID, display_name="Player", avatar_url="https://a/1.jpg"
    )
    await db_session.commit()
    assert user.steam_id == SID
    assert user.display_name == "Player"
    assert user.locale == "ru"
    assert user.roles == []


async def test_second_sign_in_reuses_it_and_refreshes_profile(db_session: AsyncSession) -> None:
    first = await upsert_user_by_steam(
        db_session, steam_id=SID, display_name="Old", avatar_url=None
    )
    await db_session.commit()
    second = await upsert_user_by_steam(
        db_session, steam_id=SID, display_name="New", avatar_url="https://a/2.jpg"
    )
    await db_session.commit()
    assert second.id == first.id
    assert second.display_name == "New"
    assert second.avatar_url == "https://a/2.jpg"
    count = (await db_session.execute(select(func.count()).select_from(User))).scalar_one()
    assert count == 1


async def test_a_missing_persona_does_not_erase_the_known_one(db_session: AsyncSession) -> None:
    await upsert_user_by_steam(
        db_session, steam_id=SID, display_name="Known", avatar_url="https://a/1.jpg"
    )
    await db_session.commit()
    user = await upsert_user_by_steam(db_session, steam_id=SID, display_name=None, avatar_url=None)
    assert user.display_name == "Known"
    assert user.avatar_url == "https://a/1.jpg"


async def test_lookup_and_roles(db_session: AsyncSession) -> None:
    user = await upsert_user_by_steam(db_session, steam_id=SID, display_name=None, avatar_url=None)
    await set_roles(db_session, user, ["admin"])
    await db_session.commit()
    found = await get_user_by_steam_id(db_session, SID)
    assert found is not None
    assert found.roles == ["admin"]
