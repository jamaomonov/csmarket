"""Alembic environment for csmarket.

Uses the same async SQLAlchemy URL as the application via ``csmarket.core.config``.
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.ext.asyncio import async_engine_from_config
from sqlalchemy.pool import NullPool

from csmarket.core.config import get_settings
from csmarket.core.db import metadata

# Import every table-owning module so autogenerate sees the whole graph.
# New modules MUST add their import here (M1: auth, users; M2: skins, fx; ...).
from csmarket.core import idempotency as _idempotency_models  # noqa: F401
from csmarket.modules.admin import models as _admin_models  # noqa: F401
from csmarket.modules.auth import models as _auth_models  # noqa: F401
from csmarket.modules.fx import models as _fx_models  # noqa: F401
from csmarket.modules.skins import models as _skins_models  # noqa: F401
from csmarket.modules.users import models as _users_models  # noqa: F401

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

settings = get_settings()
config.set_main_option("sqlalchemy.url", settings.database_url)
target_metadata = metadata


def run_migrations_offline() -> None:
    """Emit SQL without a live connection."""
    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:  # type: ignore[no-untyped-def]
    """Run migrations against a live connection."""
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """Run migrations through an async engine."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}), prefix="sqlalchemy.", poolclass=NullPool
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
