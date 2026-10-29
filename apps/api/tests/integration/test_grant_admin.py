"""``grant_admin``: grant, revoke, idempotence, unknown account."""

from __future__ import annotations

import pytest
from csmarket.modules.users.api import get_user_by_steam_id, upsert_user_by_steam
from csmarket.scripts.grant_admin import grant, main
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio
SID = "76561198000000010"


async def test_unknown_account_must_sign_in_first(db_session: AsyncSession) -> None:
    assert await grant(db_session, steam_id=SID, revoke=False) == "not_found"


async def test_grant_revoke_and_idempotence(db_session: AsyncSession) -> None:
    await upsert_user_by_steam(db_session, steam_id=SID, display_name=None, avatar_url=None)
    assert await grant(db_session, steam_id=SID, revoke=False) == "granted"
    assert await grant(db_session, steam_id=SID, revoke=False) == "unchanged"
    user = await get_user_by_steam_id(db_session, SID)
    assert user is not None
    assert user.roles == ["admin"]
    assert await grant(db_session, steam_id=SID, revoke=True) == "revoked"
    assert user.roles == []
    assert await grant(db_session, steam_id=SID, revoke=True) == "unchanged"


async def test_cli_rejects_a_malformed_steam_id(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--steam-id", "not-a-steam-id"]) == 2
    captured = capsys.readouterr()
    assert "17 digits" in captured.err
    assert "not-a-steam-id" not in captured.err + captured.out


async def test_grant_desk_adds_and_revoke_removes_only_desk(db_session: AsyncSession) -> None:
    await upsert_user_by_steam(db_session, steam_id=SID, display_name=None, avatar_url=None)
    assert await grant(db_session, steam_id=SID, revoke=False) == "granted"
    assert await grant(db_session, steam_id=SID, revoke=False, role="desk") == "granted"
    user = await get_user_by_steam_id(db_session, SID)
    assert user is not None
    assert user.roles == ["admin", "desk"]
    assert await grant(db_session, steam_id=SID, revoke=True, role="desk") == "revoked"
    assert user.roles == ["admin"]


async def test_cli_refuses_an_unknown_role() -> None:
    with pytest.raises(SystemExit):
        main(["--steam-id", SID, "--role", "root"])
