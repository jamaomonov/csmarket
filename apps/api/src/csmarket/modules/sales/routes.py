"""``/api/v1/sell*`` and ``/api/v1/sales*`` — selling skins to us (spec 2026-10-08 §5).

Routers parse and dispatch: the inventory is :mod:`.inventory`, a sale :mod:`.service`,
the reads :mod:`.views`.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.api.v1.deps import db_session
from csmarket.core.config import get_settings
from csmarket.core.errors import NotFoundError
from csmarket.core.idempotency import IDEMPOTENCY_HEADER, require_idempotency_key
from csmarket.core.money import wire_uzs
from csmarket.core.redis import get_redis
from csmarket.modules.auth.api import current_user, guard_ip
from csmarket.modules.sales.clients import deposit_client, inventory_client
from csmarket.modules.sales.inventory import priced_inventory, sell_config
from csmarket.modules.sales.schemas import (
    InventoryOut,
    PendingOut,
    SaleOut,
    SalesPage,
    SellConfigOut,
    SellIn,
)
from csmarket.modules.sales.service import create_sale
from csmarket.modules.sales.views import list_sales, owned_sale, pending_uzs, sale_out
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


async def _owned_out(db: AsyncSession, user_id: str, number: str) -> SaleOut:
    row = await owned_sale(db, user_id, number)
    if row is None:
        raise NotFoundError("sale not found")
    return sale_out(row)


@router.post(
    "/sell",
    response_model=SaleOut,
    status_code=201,
    summary="Sell skins",
    responses={200: {"model": SaleOut, "description": "replayed key"}},
)
async def post_sell(
    *,
    body: SellIn,
    request: Request,
    response: Response,
    user: Me,
    db: Db,
    client: Annotated[DepositClient, Depends(deposit_client)],
    idempotency_key: Annotated[str | None, Header(alias=IDEMPOTENCY_HEADER)] = None,
) -> SaleOut:
    """Sell the chosen items at the payout the cart showed; one Steam offer follows.

    ``Idempotency-Key`` (16..160 chars) is required; a replayed key answers 200 with the stored
    sale whatever the body says. 409 ``code``s: ``sales_disabled``, ``trade_link_missing``,
    ``trade_link_bad``, ``prices_changed`` (read the inventory again), ``below_minimum``
    (+ ``min_sum_uzs``), ``below_card_minimum`` (+ ``card_min_uzs``), ``too_many_items``,
    ``steam_refused`` (+ ``reason``), ``cards_limit``. 422 ``card_invalid``. 404 for a card
    that is not mine. 503 ``sales_unavailable`` / ``rate_unavailable``.
    """
    key = require_idempotency_key(idempotency_key)
    user_id = user.id
    await guard_ip(request, bucket="sell-create", subject=user_id)
    sale, created = await create_sale(
        db,
        redis=get_redis(),
        user=user,
        body=body,
        idempotency_key=key,
        client=client,
        settings=get_settings(),
    )
    if not created:
        response.status_code = 200
    return await _owned_out(db, user_id, sale.number)


@router.get("/sales", response_model=SalesPage, summary="My sales")
async def get_my_sales(user: Me, db: Db, cursor: str | None = None) -> SalesPage:
    """My sales, newest first, 20 a page."""
    rows, next_cursor = await list_sales(db, user.id, cursor)
    return SalesPage(items=[sale_out(r) for r in rows], next_cursor=next_cursor)


@router.get("/sales/pending", response_model=PendingOut, summary="Money on its way to my balance")
async def get_pending(user: Me, db: Db) -> PendingOut:
    """The sum my sales to the balance will credit once Steam's protection ends."""
    return PendingOut(pending_uzs=wire_uzs(await pending_uzs(db, user.id)))


@router.get(
    "/sales/{number}",
    response_model=SaleOut,
    responses={404: {"description": "Not my sale"}},
    summary="One of my sales",
)
async def get_my_sale(number: str, user: Me, db: Db) -> SaleOut:
    """The owner's sale; anyone else's, an unknown or a malformed number is a 404."""
    return await _owned_out(db, user.id, number)


__all__ = ["router"]
