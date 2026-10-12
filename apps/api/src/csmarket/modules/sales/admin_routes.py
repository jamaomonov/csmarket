"""``/api/v1/admin/sales*`` — «Выкуп»: sales, the settings (spec §7), the sales' attentions
and the per-user sell block (review 2026-10-11 SB-2, SB-3, SB-6). The payout requests live in
:mod:`.admin_payout_routes` (mounted first: ``/payouts`` must not read as a sale number).

Admin only. Every write requires an ``Idempotency-Key`` (16..160): replay lookup → the change
(:mod:`.admin_sales` / :mod:`.admin_flags`) → audit → replay row → commit; the same key on
another body is 409 ``idempotency_mismatch``. A settings save carries ``If-Match`` (the
``updated_at`` it was edited from, or ``none``): a stale tab gets 409 ``settings_stale``.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.api.v1.deps import db_session
from csmarket.modules.admin.api import remember, replayed, require_admin, required_key
from csmarket.modules.sales.admin_flags import (
    resolve_attention,
    sell_block,
    sell_blocks,
    set_sell_block,
)
from csmarket.modules.sales.admin_sales import (
    list_sales_admin,
    sale_by_number,
    save_settings,
    settings_view,
)
from csmarket.modules.sales.admin_schemas import (
    AdminSaleOut,
    AdminSalesPageOut,
    AttentionFilter,
    AttentionReasonOut,
    ResolveIn,
    SaleSettingsOut,
    SellBlockIn,
    SellBlockOut,
    SellBlocksOut,
)
from csmarket.modules.sales.rules import SaleSettings
from csmarket.modules.sales.schemas import SaleStatusOut
from csmarket.modules.users.api import User

router = APIRouter(prefix="/admin/sales", tags=["admin"], dependencies=[Depends(require_admin)])

Db = Annotated[AsyncSession, Depends(db_session)]
Admin = Annotated[User, Depends(require_admin)]
Key = Annotated[str, Depends(required_key)]


@router.get("/blocks", response_model=SellBlocksOut, summary="Users blocked from selling")
async def get_sell_blocks(db: Db) -> SellBlocksOut:
    """Every user an admin stopped from selling, newest block first."""
    return await sell_blocks(db)


@router.get(
    "/blocks/{user_id}",
    response_model=SellBlockOut,
    responses={404: {"description": "No such user"}},
    summary="Whether a user may sell",
)
async def get_sell_block(user_id: uuid.UUID, db: Db) -> SellBlockOut:
    """The user's sell block, if any."""
    return await sell_block(db, str(user_id))


@router.put(
    "/blocks/{user_id}",
    response_model=SellBlockOut,
    responses={
        404: {"description": "No such user"},
        409: {"description": "`idempotency_mismatch`"},
    },
    summary="Block or unblock a user's selling",
)
async def put_sell_block(
    user_id: uuid.UUID, body: SellBlockIn, admin: Admin, db: Db, key: Key
) -> SellBlockOut:
    """``blocked: true`` (with a ``reason``) stops the user's ``POST /sell`` (409
    ``sell_blocked``); ``false`` lifts it. Audited ``sales.user.block`` / ``unblock``."""
    uid, scope = str(user_id), "admin.sales.block"
    request = {"user_id": uid, "blocked": body.blocked, "reason": body.reason}
    if (hit := await replayed(db, scope=scope, key=key, request=request)) is not None:
        return SellBlockOut.model_validate(hit)
    await set_sell_block(
        db, user_id=uid, blocked=body.blocked, reason=body.reason, admin_id=admin.id
    )
    out = await sell_block(db, uid)
    await remember(db, scope=scope, key=key, request=request, response=out.model_dump(mode="json"))
    await db.commit()
    return out


@router.get("/settings", response_model=SaleSettingsOut, summary="The sale settings")
async def get_sale_settings(db: Db) -> SaleSettingsOut:
    """The document, who saved it and when, and the CBU rate now."""
    return await settings_view(db)


@router.put(
    "/settings",
    response_model=SaleSettingsOut,
    responses={409: {"description": "`settings_stale` or `idempotency_mismatch`"}},
    summary="Save the sale settings",
)
async def put_sale_settings(
    body: SaleSettings,
    admin: Admin,
    db: Db,
    key: Key,
    if_match: Annotated[
        str | None,
        Header(
            alias="If-Match",
            max_length=64,
            description="The `updated_at` the edit started from, or `none` (never saved). "
            "Absent: no check.",
        ),
    ] = None,
) -> SaleSettingsOut:
    """Replace the document; new sales use it, existing ones keep their numbers. ``warnings``
    name what loses money; they never refuse the save. Saved by someone else since the
    ``If-Match`` version → 409 ``settings_stale`` (reload and edit again)."""
    scope, request = "admin.sales.settings", body.model_dump(mode="json")
    if (hit := await replayed(db, scope=scope, key=key, request=request)) is not None:
        return SaleSettingsOut.model_validate(hit)
    await save_settings(db, doc=body, admin_id=admin.id, expected=if_match)
    out = await settings_view(db)
    await remember(db, scope=scope, key=key, request=request, response=out.model_dump(mode="json"))
    await db.commit()
    return out


@router.get("", response_model=AdminSalesPageOut, summary="Sales")
async def get_sales(
    *,
    db: Db,
    status: SaleStatusOut | None = None,
    q: Annotated[str | None, Query(max_length=8)] = None,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    attention: AttentionFilter | None = None,
    reason: AttentionReasonOut | None = None,
) -> AdminSalesPageOut:
    """Newest first; ``q`` is a number prefix in any case. ``attention=open`` keeps the sales
    waiting for an admin (``resolved``: already checked, ``any``: either); ``reason`` one
    attention reason. ``attention_open`` counts every open one, whatever the filters."""
    return await list_sales_admin(
        db,
        status=status,
        q=q,
        cursor=cursor,
        limit=limit,
        attention=attention,
        reason=reason,
    )


@router.get(
    "/{number}",
    response_model=AdminSaleOut,
    responses={404: {"description": "No such sale"}},
    summary="A sale",
)
async def get_sale(number: str, db: Db) -> AdminSaleOut:
    """Statuses, Skinslink's amount, our payout and margin, the items, the payout request."""
    return await sale_by_number(db, number)


@router.post(
    "/{number}/resolve",
    response_model=AdminSaleOut,
    responses={
        404: {"description": "No such sale"},
        409: {"description": "`nothing_to_resolve` or `idempotency_mismatch`"},
    },
    summary="Mark a sale's attention as checked",
)
async def post_resolve(
    number: str, body: ResolveIn, admin: Admin, db: Db, key: Key
) -> AdminSaleOut:
    """«Проверено» (an optional note): stamps ``resolved_at/by/note`` once, audited
    ``sales.attention.resolve``; already resolved → unchanged. A new attention reason on the
    sale later opens it again."""
    note = body.note or None
    scope, request = "admin.sales.resolve", {"number": number, "note": note}
    if (hit := await replayed(db, scope=scope, key=key, request=request)) is not None:
        return AdminSaleOut.model_validate(hit)
    sale = await resolve_attention(db, number=number, admin_id=admin.id, note=note)
    out = await sale_by_number(db, sale.number)  # read fresh: the flush expired it
    await remember(db, scope=scope, key=key, request=request, response=out.model_dump(mode="json"))
    await db.commit()
    return out


__all__ = ["router"]
