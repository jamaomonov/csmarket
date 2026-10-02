"""Dev-only: the signed-in user's letters from the dev transport (M4b ruling R6).

404 unless ``settings.dev_login_active`` (never in prod); not in the OpenAPI schema. e2e
reads the email confirmation link here.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends

from csmarket.api.v1.deps import dev_gate
from csmarket.core.redis import get_redis
from csmarket.modules.auth.api import current_user
from csmarket.modules.notifications.dev_transport import DevTransport
from csmarket.modules.users.api import User

router = APIRouter(prefix="/dev", tags=["dev"], dependencies=[Depends(dev_gate)])


# Any: the stored letters are free-form JSON objects (dev only).
@router.get("/emails", include_in_schema=False)
async def dev_emails(
    user: Annotated[User, Depends(current_user)], kind: str | None = None
) -> list[dict[str, Any]]:
    """The caller's letters kept by the dev transport, newest first."""
    return await DevTransport(get_redis()).letters(user_id=user.id, kind=kind)
