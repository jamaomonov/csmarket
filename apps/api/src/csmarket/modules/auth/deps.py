"""FastAPI dependency resolving the signed-in user from ``Authorization: Bearer``."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.api.v1.deps import db_session
from csmarket.core.errors import AccountSuspendedError, UnauthorizedError
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
    db: AsyncSession = Depends(db_session, scope="function"),  # noqa: B008
) -> User:
    """The authenticated user; 401 when absent/invalid, 403 when banned."""
    return await resolve_current_user(db, bearer_token(authorization))


async def optional_user(
    authorization: Annotated[str | None, Header()] = None,
    db: AsyncSession = Depends(db_session, scope="function"),  # noqa: B008
) -> User | None:
    """The signed-in user, or ``None`` — never an error: for public routes where signing in is
    optional (an article's like). A missing, invalid or expired token, or a suspended account,
    reads as anonymous."""
    if not authorization:
        return None
    try:
        return await resolve_current_user(db, bearer_token(authorization))
    except (UnauthorizedError, AccountSuspendedError):
        return None
