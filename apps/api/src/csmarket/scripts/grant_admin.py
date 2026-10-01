"""Grant or revoke the ``admin`` role by Steam ID (ruling P5).

Run inside the api container::

    docker compose exec api python -m csmarket.scripts.grant_admin --steam-id 7656119XXXXXXXXXX
    docker compose exec api python -m csmarket.scripts.grant_admin --steam-id 7656119XXXXXXXXXX --revoke

The account must exist: the person signs in with Steam once first. The script prints
only an outcome word — never the Steam ID — because its output ends up in shell history
and logs.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

# Registers ``refresh_tokens`` (FK to ``users``) in this standalone process so the metadata
# is complete, as in the app; nothing else here imports ``auth``.
import csmarket.modules.auth.models  # noqa: F401
from csmarket.core.db import dispose_engine, get_session_factory
from csmarket.modules.users.api import get_user_by_steam_id, set_roles

Outcome = Literal["granted", "revoked", "unchanged", "not_found"]


async def grant(db: AsyncSession, *, steam_id: str, revoke: bool) -> Outcome:
    """Add or remove ``admin``; flushes, the caller commits."""
    user = await get_user_by_steam_id(db, steam_id)
    if user is None:
        return "not_found"
    has = "admin" in user.roles
    if revoke and has:
        await set_roles(db, user, [r for r in user.roles if r != "admin"])
        return "revoked"
    if not revoke and not has:
        await set_roles(db, user, [*user.roles, "admin"])
        return "granted"
    return "unchanged"


async def _main(steam_id: str, *, revoke: bool) -> int:
    factory = get_session_factory()
    try:
        async with factory() as db:
            outcome = await grant(db, steam_id=steam_id, revoke=revoke)
            await db.commit()
    finally:
        await dispose_engine()
    print(outcome)
    return 1 if outcome == "not_found" else 0


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--steam-id", required=True, help="steamid64 (17 digits)")
    parser.add_argument("--revoke", action="store_true")
    args = parser.parse_args(argv)
    if not (args.steam_id.isdigit() and len(args.steam_id) == 17):
        print("steam id must be 17 digits", file=sys.stderr)
        return 2
    return asyncio.run(_main(args.steam_id, revoke=args.revoke))


if __name__ == "__main__":
    raise SystemExit(main())
