"""Dev-only order routes: pay an order through the ``mock`` kassa without a kassa page, and
move its trade at the dev Waxpeer fake (accept / decline / roll back).

Every route here answers 404 unless ``settings.dev_login_active`` (never in prod), and none
is in the OpenAPI schema. The trade route also needs the fake on (``waxpeer_fake``).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.api.v1.deps import db_session, dev_gate
from csmarket.core.errors import NotFoundError
from csmarket.modules.auth.api import current_user
from csmarket.modules.orders.paying import dev_pay
from csmarket.modules.orders.schemas import OrderOut
from csmarket.modules.orders.service import get_owned
from csmarket.modules.skins.api import FakeAction, FakeTradeClient, WaxpeerTrade, fake_client
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


class DevTradeIn(BaseModel):
    """What to do with the order's trade at the fake."""

    model_config = ConfigDict(extra="forbid")

    action: FakeAction


@router.post("/{number}/trade", response_model=WaxpeerTrade, include_in_schema=False)
async def dev_move_trade(
    number: str,
    body: DevTradeIn,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[AsyncSession, Depends(db_session)],
    fake: Annotated[FakeTradeClient, Depends(fake_client)],
) -> WaxpeerTrade:
    """Accept, decline or roll back the owner's trade at the fake; the trade as it now is.

    The order moves when the reconcile sweep next reads the trade, as with Waxpeer.
    Keyless on purpose: dev-only, and a repeat of an action already done is a no-op.
    """
    row = await get_owned(db, user.id, number)
    if row is None:
        raise NotFoundError("order not found")
    waxpeer_id = row.trade.waxpeer_id if row.trade is not None else None
    await db.commit()  # nothing held while Redis answers
    return await fake.act(row.order.id, body.action, waxpeer_id=waxpeer_id)


__all__ = ["router"]
