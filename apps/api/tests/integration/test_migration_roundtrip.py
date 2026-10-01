"""The newest migration goes down and back up cleanly, on a database of its own.

A scratch database in this worker's container: altering the shared test schema under
the session's pooled connections would invalidate their cached statements. ``env.py``
takes its URL from the settings, so the test points ``CSMARKET_DATABASE_URL`` at the
scratch database (and clears the settings cache both ways).
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from csmarket.core import config as app_config
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

_SCRATCH = "csmarket_migration_roundtrip"


def _alembic(url: str) -> Config:
    api_dir = Path(__file__).resolve().parents[2]
    cfg = Config(str(api_dir / "alembic.ini"))
    cfg.set_main_option("script_location", str(api_dir / "migrations"))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


async def _admin(url: str, sql: str) -> None:
    engine = create_async_engine(url, isolation_level="AUTOCOMMIT")
    async with engine.connect() as conn:
        await conn.execute(text(sql))
    await engine.dispose()


async def _revoked_reason_column(url: str) -> list[str]:
    engine = create_async_engine(url)
    async with engine.connect() as conn:
        rows = await conn.execute(
            text(
                "SELECT column_name FROM information_schema.columns"
                " WHERE table_name = 'refresh_tokens' AND column_name = 'revoked_reason'"
            )
        )
        names = [r[0] for r in rows]
    await engine.dispose()
    return names


def test_0011_refresh_revoked_reason_downgrades_and_upgrades(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shared = make_url(os.environ["CSMARKET_DATABASE_URL"])
    scratch = shared.set(database=_SCRATCH).render_as_string(hide_password=False)
    admin = shared.render_as_string(hide_password=False)
    asyncio.run(_admin(admin, f"DROP DATABASE IF EXISTS {_SCRATCH}"))
    asyncio.run(_admin(admin, f"CREATE DATABASE {_SCRATCH}"))
    monkeypatch.setenv("CSMARKET_DATABASE_URL", scratch)
    app_config.get_settings.cache_clear()
    try:
        cfg = _alembic(scratch)
        command.upgrade(cfg, "head")
        assert asyncio.run(_revoked_reason_column(scratch)) == ["revoked_reason"]
        command.downgrade(cfg, "0010_uzum_transactions")
        assert asyncio.run(_revoked_reason_column(scratch)) == []
        command.upgrade(cfg, "head")
        assert asyncio.run(_revoked_reason_column(scratch)) == ["revoked_reason"]
    finally:
        monkeypatch.setenv("CSMARKET_DATABASE_URL", admin)
        app_config.get_settings.cache_clear()
        asyncio.run(_admin(admin, f"DROP DATABASE IF EXISTS {_SCRATCH} WITH (FORCE)"))


async def _orders_schema(url: str) -> tuple[list[str], list[str]]:
    """The order tables present, and the ``payments`` constraints that tie payments to them."""
    engine = create_async_engine(url)
    async with engine.connect() as conn:
        tables = await conn.execute(
            text(
                "SELECT table_name FROM information_schema.tables"
                " WHERE table_name IN ('orders', 'skin_trades') ORDER BY table_name"
            )
        )
        constraints = await conn.execute(
            text(
                "SELECT conname FROM pg_constraint WHERE conname IN"
                " ('ck_payments_purpose_order', 'fk_payments_order_id_orders') ORDER BY conname"
            )
        )
        found = ([r[0] for r in tables], [r[0] for r in constraints])
    await engine.dispose()
    return found


def test_0013_orders_skin_trades_downgrades_and_upgrades(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shared = make_url(os.environ["CSMARKET_DATABASE_URL"])
    scratch = shared.set(database=_SCRATCH).render_as_string(hide_password=False)
    admin = shared.render_as_string(hide_password=False)
    present = (
        ["orders", "skin_trades"],
        ["ck_payments_purpose_order", "fk_payments_order_id_orders"],
    )
    asyncio.run(_admin(admin, f"DROP DATABASE IF EXISTS {_SCRATCH}"))
    asyncio.run(_admin(admin, f"CREATE DATABASE {_SCRATCH}"))
    monkeypatch.setenv("CSMARKET_DATABASE_URL", scratch)
    app_config.get_settings.cache_clear()
    try:
        cfg = _alembic(scratch)
        command.upgrade(cfg, "head")
        assert asyncio.run(_orders_schema(scratch)) == present
        command.downgrade(cfg, "0012_payments_number_pattern_ops")
        assert asyncio.run(_orders_schema(scratch)) == ([], [])
        command.upgrade(cfg, "head")
        assert asyncio.run(_orders_schema(scratch)) == present
    finally:
        monkeypatch.setenv("CSMARKET_DATABASE_URL", admin)
        app_config.get_settings.cache_clear()
        asyncio.run(_admin(admin, f"DROP DATABASE IF EXISTS {_SCRATCH} WITH (FORCE)"))
