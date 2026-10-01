"""FastAPI dependencies for admin endpoints.

Role model: spec §2.10. Admin gates resolve the current user via the ``auth`` module and
then check membership in ``users.roles``. The role is read from the database on every
request, so the next request after a ``roles`` update reflects the change.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends

from csmarket.core.errors import ForbiddenError
from csmarket.modules.auth.api import current_user
from csmarket.modules.users.models import User


def has_role(user: User, role: str) -> bool:
    """Return ``True`` if ``user`` carries ``role`` (case-sensitive)."""
    return role in (user.roles or [])


async def require_admin(user: Annotated[User, Depends(current_user)]) -> User:
    """FastAPI dependency: the current user if they are an admin, 403 otherwise.

    A non-admin Bearer token deliberately returns **403 Forbidden**, not 401, so the admin
    SPA can tell "not signed in" (401) from "signed in but not allowed" (403).
    """
    if not has_role(user, "admin"):
        raise ForbiddenError("admin role required")
    return user


__all__ = ["has_role", "require_admin"]
