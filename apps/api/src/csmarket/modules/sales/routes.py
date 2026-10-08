"""``/api/v1/sell*`` and ``/api/v1/sales*`` — selling skins to us (spec 2026-10-08 §5).

Routers parse and dispatch: the inventory is :mod:`.inventory`, a sale :mod:`.service`,
the reads :mod:`.views`.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.api.v1.deps import db_session
from csmarket.core.config import get_settings
from csmarket.core.redis import get_redis
from csmarket.modules.auth.api import current_user, guard_ip
from csmarket.modules.sales.clients import inventory_client
from csmarket.modules.sales.inventory import priced_inventory, sell_config
from csmarket.modules.sales.schemas import InventoryOut, SellConfigOut
from csmarket.modules.skinslink.api import DepositClient
from csmarket.modules.users.api import User

router = APIRouter(tags=["sales"])

Db = Annotated[AsyncSession, Depends(db_session)]
Me = Annotated[User, Depends(current_user)]


@router.get("/sell/config", response_model=SellConfigOut, summary="How selling works now")
async def get_sell_config(db: Db) -> SellConfigOut:
    """Public: whether selling is on, the bonus, the card fees and minimums."""
    return await sell_config(db, get_redis(), get_settings())


@router.get("/sell/inventory", response_model=InventoryOut, summary="My inventory, priced")
async def get_sell_inventory(
    *,
    request: Request,
    user: Me,
    db: Db,
    client: Annotated[DepositClient, Depends(inventory_client)],
    refresh: bool = False,
) -> InventoryOut:
    """The items we buy now, at our soʻm prices; kept 5 minutes, ``?refresh=1`` asks again.

    409 ``code``s: ``sales_disabled``, ``trade_link_missing``, ``trade_link_bad`` (+ ``reason``),
    ``steam_refused`` (+ ``reason``: Skinslink's Steam account code). 503 ``sales_unavailable``
    or ``rate_unavailable``.
    """
    user_id = user.id
    await guard_ip(request, bucket="sell-inventory", subject=user_id)
    return await priced_inventory(
        db,
        redis=get_redis(),
        user=user,
        client=client,
        settings=get_settings(),
        refresh=refresh,
    )


__all__ = ["router"]
