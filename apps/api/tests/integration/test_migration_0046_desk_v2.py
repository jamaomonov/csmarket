"""``0046_desk_v2`` gives every desk item without a picture our catalogue's one, on a
database of its own (as ``test_migration_roundtrip``)."""

from __future__ import annotations

import asyncio
import os

import pytest
from alembic import command
from csmarket.core import config as app_config
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from tests.integration.test_migration_roundtrip import _admin, _alembic

_SCRATCH = "csmarket_migration_0046"
_DEAL = "01900000-0000-7000-8000-000000000001"
_SEED = [
    (
        "INSERT INTO skin_items (id, market_hash_name, phase, slug, category, search_text, image_url)"
        " VALUES ('01900000-0000-7000-8000-0000000000a1', 'Knife', 'Phase 1', 'k1', 'knives', 'k',"
        " 'https://img.test/phase.png'),"
        " ('01900000-0000-7000-8000-0000000000a2', 'Knife', '', 'k0', 'knives', 'k',"
        " 'https://img.test/plain.png')"
    ),
    f"INSERT INTO desk_deals (id, status, trader) VALUES ('{_DEAL}', 'agreed', 't')",
    (
        "INSERT INTO desk_items (id, deal_id, name, destination, image_url) VALUES"
        f" ('01900000-0000-7000-8000-0000000000b1', '{_DEAL}', 'Knife', 'stock', NULL),"
        f" ('01900000-0000-7000-8000-0000000000b2', '{_DEAL}', 'Knife', 'stock', 'https://own'),"
        f" ('01900000-0000-7000-8000-0000000000b3', '{_DEAL}', 'Nothing', 'stock', NULL)"
    ),
]


async def _run(url: str, statements: list[str]) -> None:
    engine = create_async_engine(url)
    async with engine.begin() as conn:
        for sql in statements:
            await conn.execute(text(sql))
    await engine.dispose()


async def _pictures(url: str) -> list[str | None]:
    engine = create_async_engine(url)
    async with engine.connect() as conn:
        rows = await conn.execute(text("SELECT image_url FROM desk_items ORDER BY id"))
        found = [r[0] for r in rows]
    await engine.dispose()
    return found


def test_0046_fills_desk_pictures_from_the_catalogue(monkeypatch: pytest.MonkeyPatch) -> None:
    shared = make_url(os.environ["CSMARKET_DATABASE_URL"])
    scratch = shared.set(database=_SCRATCH).render_as_string(hide_password=False)
    admin = shared.render_as_string(hide_password=False)
    asyncio.run(_admin(admin, f"DROP DATABASE IF EXISTS {_SCRATCH}"))
    asyncio.run(_admin(admin, f"CREATE DATABASE {_SCRATCH}"))
    monkeypatch.setenv("CSMARKET_DATABASE_URL", scratch)
    app_config.get_settings.cache_clear()
    try:
        cfg = _alembic(scratch)
        command.upgrade(cfg, "0045_desk_bot")
        asyncio.run(_run(scratch, _SEED))
        command.upgrade(cfg, "0046_desk_v2")
        assert asyncio.run(_pictures(scratch)) == [
            "https://img.test/plain.png",
            "https://own",
            None,
        ]
        command.downgrade(cfg, "0045_desk_bot")
        command.upgrade(cfg, "head")
    finally:
        monkeypatch.setenv("CSMARKET_DATABASE_URL", admin)
        app_config.get_settings.cache_clear()
        asyncio.run(_admin(admin, f"DROP DATABASE IF EXISTS {_SCRATCH} WITH (FORCE)"))
