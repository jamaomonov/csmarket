"""FastAPI dependencies for admin endpoints.

Role model: spec §2.10. Admin gates resolve the current user via the ``auth`` module and
then check membership in ``users.roles``. The role is read from the database on every
request, so the next request after a ``roles`` update reflects the change.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header

from csmarket.core.errors import ForbiddenError, ValidationError
from csmarket.core.idempotency import IDEMPOTENCY_HEADER, normalize_idempotency_key
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


#: ``idempotent_responses.idempotency_key`` is ``varchar(160)``.
_MAX_KEY_LENGTH = 160


def required_key(value: Annotated[str, Header(alias=IDEMPOTENCY_HEADER)]) -> str:
    """The ``Idempotency-Key`` every admin write must carry: 16 to 160 characters.

    Declared required, so the schema says so and a missing header is FastAPI's 422; one
    present but too short or too long is our 422 ``validation`` naming the header.
    """
    key = normalize_idempotency_key(value)
    if key is None or len(key) > _MAX_KEY_LENGTH:
        raise ValidationError(
            f"{IDEMPOTENCY_HEADER} header of 16 to {_MAX_KEY_LENGTH} characters is required",
            header=IDEMPOTENCY_HEADER,
        )
    return key


__all__ = ["has_role", "require_admin", "required_key"]
