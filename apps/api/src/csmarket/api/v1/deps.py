"""Shared FastAPI dependencies used by ``/api/v1`` routes."""

from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.config import get_settings
from csmarket.core.db import get_session
from csmarket.core.errors import NotFoundError


async def db_session() -> AsyncIterator[AsyncSession]:
    """Yield a transactional async session per request."""
    async for session in get_session():
        yield session


SessionDep = Depends(db_session)


def dev_gate() -> None:
    """404 unless ``dev_login_active`` (never in prod) — the dependency of every ``/dev``
    router, run before auth and the body like any unknown path."""
    if not get_settings().dev_login_active:
        raise NotFoundError("not found")
