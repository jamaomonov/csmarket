"""FastAPI dependency resolving the signed-in user from ``Authorization: Bearer``."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.api.v1.deps import db_session
from csmarket.core.errors import UnauthorizedError
from csmarket.modules.auth.service import resolve_current_user
from csmarket.modules.users.models import User


def bearer_token(authorization: str | None) -> str:
    """The token from a ``Bearer`` header, or 401."""
    if not authorization:
        raise UnauthorizedError("missing Authorization header")
    scheme, _, token = authorization.partition(" ")
    if scheme != "Bearer" or not token.strip():
        raise UnauthorizedError("invalid Authorization scheme")
    return token.strip()


async def current_user(
    authorization: Annotated[str | None, Header()] = None,
    db: AsyncSession = Depends(db_session),  # noqa: B008
) -> User:
    """The authenticated user; 401 when absent/invalid, 403 when banned."""
    return await resolve_current_user(db, bearer_token(authorization))
