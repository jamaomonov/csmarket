"""Dev-only order routes: pay an order through the ``mock`` kassa without a kassa page.

Every route here answers 404 unless ``settings.dev_login_active`` (never in prod), and none
is in the OpenAPI schema.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.api.v1.deps import db_session, dev_gate
from csmarket.modules.auth.api import current_user
from csmarket.modules.orders.paying import dev_pay
from csmarket.modules.orders.schemas import OrderOut
from csmarket.modules.users.api import User

router = APIRouter(prefix="/dev/orders", tags=["dev"], dependencies=[Depends(dev_gate)])


@router.post("/{number}/pay", response_model=OrderOut, include_in_schema=False)
async def dev_pay_order(
    number: str,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[AsyncSession, Depends(db_session)],
) -> OrderOut:
    """Settle the owner's order through ``mock`` (the real ``settle`` hook).

    Keyless on purpose: dev-only, and a repeat is a no-op — a paid order is returned as is
    and ``settle`` pays an order once.
    """
    return await dev_pay(db, user_id=user.id, number=number)


__all__ = ["router"]
