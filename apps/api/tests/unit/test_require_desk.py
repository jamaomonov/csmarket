"""``require_desk``: the owner's own section needs ``admin`` and ``desk`` (spec 2026-10-29-desk)."""

from __future__ import annotations

import pytest
from csmarket.core.errors import ForbiddenError
from csmarket.modules.admin.api import require_admin, require_desk
from csmarket.modules.users.models import User

pytestmark = pytest.mark.asyncio


def _user(*roles: str) -> User:
    return User(id="u1", steam_id="76561198000000001", roles=list(roles))


async def test_admin_without_desk_is_403() -> None:
    with pytest.raises(ForbiddenError):
        await require_desk(await require_admin(_user("admin")))


async def test_admin_with_desk_passes() -> None:
    user = _user("admin", "desk")
    assert await require_desk(await require_admin(user)) is user


async def test_customer_with_desk_but_no_admin_is_403() -> None:
    with pytest.raises(ForbiddenError):
        await require_desk(await require_admin(_user("desk")))
