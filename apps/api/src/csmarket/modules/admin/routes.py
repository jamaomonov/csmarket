"""``/api/v1/admin`` — M1 has only the identity probe the SPA's AuthGuard calls."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from csmarket.modules.admin.deps import require_admin
from csmarket.modules.users.models import User
from csmarket.modules.users.schemas import MeOut

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/me", response_model=MeOut, summary="The signed-in admin")
async def admin_me(user: Annotated[User, Depends(require_admin)]) -> MeOut:
    """200 for an admin, 403 for anyone else signed in, 401 without a token."""
    return MeOut.of(user)
