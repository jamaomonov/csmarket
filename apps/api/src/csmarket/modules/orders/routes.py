"""Customer order routes: checkout (``POST /orders``), paying it, one order, ``/me/orders``.

Routers parse and dispatch; checkout lives in :mod:`csmarket.modules.orders.checkout`,
paying in :mod:`csmarket.modules.orders.paying`, reads in :mod:`csmarket.modules.orders.service`.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.api.v1.deps import db_session
from csmarket.core.config import get_settings
from csmarket.core.errors import NotFoundError
from csmarket.core.idempotency import IDEMPOTENCY_HEADER, require_idempotency_key
from csmarket.core.redis import get_redis
from csmarket.modules.auth.api import current_user, guard_ip
from csmarket.modules.orders.checkout import create_order
from csmarket.modules.orders.paying import pay_order
from csmarket.modules.orders.schemas import (
    OrderCreateIn,
    OrderOut,
    OrderPayIn,
    OrderPayOut,
    OrdersPage,
)
from csmarket.modules.orders.service import get_owned, list_for_user, order_out
from csmarket.modules.skins.api import SearchClient, search_client
from csmarket.modules.users.api import User

router = APIRouter(prefix="/orders", tags=["orders"])
me_router = APIRouter(prefix="/me", tags=["orders"])


async def _owned_out(db: AsyncSession, user_id: str, number: str) -> OrderOut:
    row = await get_owned(db, user_id, number)
    if row is None:
        raise NotFoundError("order not found")
    return order_out(row.order, row.trade, row.image_url, row.purchase)


@router.post(
    "",
    response_model=OrderOut,
    status_code=201,
    summary="Buy one skin",
    responses={200: {"model": OrderOut, "description": "replayed key"}},
)
async def post_order(
    *,
    body: OrderCreateIn,
    request: Request,
    response: Response,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[AsyncSession, Depends(db_session)],
    client: Annotated[SearchClient, Depends(search_client)],
    idempotency_key: Annotated[str | None, Header(alias=IDEMPOTENCY_HEADER)] = None,
) -> OrderOut:
    """Open an order for the chosen offer at the price the panel showed.

    ``Idempotency-Key`` (16..160 chars) is required. A replayed key answers 200 with the
    stored order, whatever the body says. 409 ``code``s: ``buying_disabled``,
    ``trade_link_missing``, ``trade_link_bad`` (+ ``reason``), ``price_changed`` (+ the new
    ``price_uzs``), ``offer_gone`` (+ ``next_offer`` or ``null``). 404 for an unknown item;
    503 ``rate_unavailable`` without a fresh soʻm rate.
    """
    key = require_idempotency_key(idempotency_key)
    user_id = user.id  # checkout ends the session's transaction: read it first
    await guard_ip(request, bucket="order-create", subject=user_id)
    order, created = await create_order(
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
    return await _owned_out(db, user_id, order.number)


@router.post("/{number}/pay", response_model=OrderPayOut, summary="Pay one of my orders")
async def post_order_pay(
    *,
    number: str,
    body: OrderPayIn,
    request: Request,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[AsyncSession, Depends(db_session)],
    idempotency_key: Annotated[str | None, Header(alias=IDEMPOTENCY_HEADER)] = None,
) -> OrderPayOut:
    """Pay from the balance (the order is ``paid`` at once) or get a kassa's payment page.

    ``Idempotency-Key`` (16..160 chars) is required; the same key and body replay the first
    answer, another body is 409 ``idempotency_mismatch``. 409 ``code``s:
    ``order_not_payable`` (+ ``reason``: ``paid`` | ``expired``), ``balance_too_low``.
    422 ``order_provider`` for a kassa not available here. Another user's order is a 404.
    """
    key = require_idempotency_key(idempotency_key)
    user_id = user.id
    await guard_ip(request, bucket="order-pay", subject=user_id)
    return await pay_order(
        db,
        user_id=user_id,
        number=number,
        provider=body.provider,
        locale=body.locale,
        idempotency_key=key,
    )


@router.get("/{number}", response_model=OrderOut, summary="One of my orders")
async def get_order(
    number: str,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[AsyncSession, Depends(db_session)],
) -> OrderOut:
    """The owner's order; anyone else's, an unknown or a malformed number is a 404."""
    return await _owned_out(db, user.id, number)


@me_router.get("/orders", response_model=OrdersPage, summary="My orders")
async def get_my_orders(
    user: Annotated[User, Depends(current_user)],
    db: Annotated[AsyncSession, Depends(db_session)],
    cursor: str | None = None,
) -> OrdersPage:
    """My orders, newest first, 20 a page; cancelled and expired unpaid ones are left out."""
    rows, next_cursor = await list_for_user(db, user.id, cursor)
    return OrdersPage(
        items=[order_out(r.order, r.trade, r.image_url, r.purchase) for r in rows],
        next_cursor=next_cursor,
    )


__all__ = ["me_router", "router"]
