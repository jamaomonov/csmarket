"""``/api/v1/admin/orders`` and ``/api/v1/admin/trades`` — find orders, the trades page and
its attention queue, one order's page, and the three actions on it: «Разобрано» (resolve),
refund to the balance, retry the buy.

Admin only (``require_admin`` on the whole router). Every write requires an
``Idempotency-Key`` of 16..160 characters and runs: lock the order, then its trade
(ruling K) → replay lookup → the change (``orders.api``) → ``audit.record`` → replay row →
commit. A replayed key returns the stored page and writes nothing; the same key on another
request is 409 ``idempotency_mismatch``.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.api.v1.deps import db_session
from csmarket.modules.admin import orders_service as svc
from csmarket.modules.admin.audit import record
from csmarket.modules.admin.deps import require_admin, required_key
from csmarket.modules.admin.filters import text_filter
from csmarket.modules.admin.orders_schemas import (
    AdminOrderDetail,
    AdminOrdersOut,
    AdminResolveIn,
    AdminTradesOut,
    TradesView,
)
from csmarket.modules.admin.users_service import remember, replayed
from csmarket.modules.orders.api import (
    OrderStatusOut,
    admin_refund,
    lock_order,
    resolve_attention,
    retry_buy,
)
from csmarket.modules.users.api import User

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])

Db = Annotated[AsyncSession, Depends(db_session)]
Admin = Annotated[User, Depends(require_admin)]
Key = Annotated[str, Depends(required_key)]

_NOT_FOUND: dict[int | str, dict[str, Any]] = {404: {"description": "No such order"}}
_IDEMPOTENCY = "`idempotency_mismatch` — the key answered another request."


def _conflicts(*lines: str) -> dict[int | str, dict[str, Any]]:
    """The 409 codes a write answers with (``code`` in the problem body)."""
    text = "Conflict; `code` is one of:\n\n" + "\n".join(f"- {line}" for line in lines)
    return {**_NOT_FOUND, 409: {"description": text}}


async def _finish(
    db: AsyncSession, number: str, *, scope: str, key: str, request: dict[str, Any]
) -> AdminOrderDetail:
    """Build the order's page, store it as the replay, commit (after the change and audit)."""
    detail = await svc.order_detail(db, number)
    await remember(
        db, scope=scope, key=key, request=request, response=detail.model_dump(mode="json")
    )
    await db.commit()
    return detail


@router.get("/orders", response_model=AdminOrdersOut, summary="Find orders")
async def list_orders(
    db: Db,
    *,
    q: Annotated[str | None, text_filter(100)] = None,
    status: OrderStatusOut | None = None,
    user_id: uuid.UUID | None = None,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> AdminOrdersOut:
    """Newest first; ``q`` = a number prefix (any case) or part of the item's name."""
    items, next_cursor = await svc.list_orders(
        db,
        q=q,
        status=status,
        user_id=str(user_id) if user_id is not None else None,
        cursor=cursor,
        limit=limit,
    )
    return AdminOrdersOut(items=items, next_cursor=next_cursor)


@router.get("/trades", response_model=AdminTradesOut, summary="Trades and the attention queue")
async def list_trades(
    db: Db,
    *,
    view: TradesView = "all",
    q: Annotated[str | None, text_filter(100)] = None,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> AdminTradesOut:
    """Orders with a trade, newest first: ``all``, ``active`` or ``attention``; the tab
    counts ignore ``q``."""
    items, counts, next_cursor = await svc.list_trades(
        db, view=view, q=q, cursor=cursor, limit=limit
    )
    return AdminTradesOut(items=items, counts=counts, next_cursor=next_cursor)


@router.get(
    "/orders/{number}", response_model=AdminOrderDetail, responses=_NOT_FOUND, summary="An order"
)
async def get_order(number: str, db: Db) -> AdminOrderDetail:
    """The order (trade link masked), its buyer, trade, payments, and what may be done."""
    return await svc.order_detail(db, number)


@router.post(
    "/orders/{number}/resolve",
    response_model=AdminOrderDetail,
    responses=_conflicts(
        "`nothing_to_resolve` — the order has no trade, or its trade no attention.",
        _IDEMPOTENCY,
    ),
    summary="Mark the trade's attention as checked",
)
async def resolve(
    number: str, body: AdminResolveIn, admin: Admin, db: Db, key: Key
) -> AdminOrderDetail:
    """«Разобрано»: stamps ``resolved_at/by/note`` once; already resolved → unchanged."""
    await lock_order(db, number)
    note = body.note or None
    request = {"number": number, "note": note}
    scope = "admin.orders.resolve"
    if (hit := await replayed(db, scope=scope, key=key, request=request)) is not None:
        return AdminOrderDetail.model_validate(hit)
    reason = await resolve_attention(db, number=number, admin_id=admin.id, note=note)
    if reason is not None:
        await record(
            db,
            actor_id=admin.id,
            action="orders.trade.resolve",
            target_type="order",
            target_id=number,
            payload={"reason": reason},
        )
    return await _finish(db, number, scope=scope, key=key, request=request)


@router.post(
    "/orders/{number}/refund",
    response_model=AdminOrderDetail,
    responses=_conflicts(
        "`already_refunded` — the money is already on the balance.",
        "`order_in_flight` — the skin may still reach the buyer (or the attention is "
        "unresolved, or not a «nothing was bought» case).",
        "`order_not_refundable` — settled with nothing to give back (unpaid, cancelled, "
        "delivered).",
        "`order_busy` — a buy attempt is running; try again in a few minutes.",
        _IDEMPOTENCY,
    ),
    summary="Refund the order to the buyer's balance",
)
async def refund(number: str, admin: Admin, db: Db, key: Key) -> AdminOrderDetail:
    """Only a ``buying`` order whose resolved attention says nothing was bought
    (``can_refund``); the order becomes ``failed`` (reason ``admin``)."""
    await lock_order(db, number)
    request = {"number": number}
    scope = "admin.orders.refund"
    if (hit := await replayed(db, scope=scope, key=key, request=request)) is not None:
        return AdminOrderDetail.model_validate(hit)
    order = await admin_refund(db, number=number, admin_id=admin.id)
    await record(
        db,
        actor_id=admin.id,
        action="orders.refund",
        target_type="order",
        target_id=number,
        payload={"amount_uzs": int(order.price_uzs)},
    )
    return await _finish(db, number, scope=scope, key=key, request=request)


@router.post(
    "/orders/{number}/retry",
    response_model=AdminOrderDetail,
    responses=_conflicts(
        "`not_retryable` — not a `buying`, unrefunded order with a resolved "
        "`buy_unconfirmed`, `ambiguous_trade` or `waxpeer_forbidden` attention.",
        "`order_busy` — a buy attempt is running; try again in a few minutes.",
        _IDEMPOTENCY,
    ),
    summary="Retry the order's buy",
)
async def retry(number: str, admin: Admin, db: Db, key: Key) -> AdminOrderDetail:
    """Clears the resolved attention and makes the buy due now (``can_retry``); the next
    attempt looks the project id up first, so a purchase Waxpeer made is adopted."""
    await lock_order(db, number)
    request = {"number": number}
    scope = "admin.orders.retry"
    if (hit := await replayed(db, scope=scope, key=key, request=request)) is not None:
        return AdminOrderDetail.model_validate(hit)
    reason = await retry_buy(db, number=number, admin_id=admin.id)
    await record(
        db,
        actor_id=admin.id,
        action="orders.buy.retry",
        target_type="order",
        target_id=number,
        payload={"reason": reason},
    )
    return await _finish(db, number, scope=scope, key=key, request=request)


__all__ = ["router"]
