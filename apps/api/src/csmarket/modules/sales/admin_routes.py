"""``/api/v1/admin/sales*`` — «Выкуп»: payout requests, sales, the settings (spec §7), the
sales' attentions and the per-user sell block (review 2026-10-11 SB-2, SB-3, SB-6).

Admin only. Every write requires an ``Idempotency-Key`` (16..160): replay lookup → the change
(:mod:`.admin_payouts` / :mod:`.admin_sales`) → audit → replay row → commit; the same key on
another body is 409 ``idempotency_mismatch``. The reveal is keyless on purpose: it changes
nothing but the audit trail, each reveal is its own audit row, and a replay would have to
store the card number.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.api.v1.deps import db_session
from csmarket.modules.admin.api import record, remember, replayed, require_admin, required_key
from csmarket.modules.sales.admin_flags import (
    resolve_attention,
    sell_block,
    sell_blocks,
    set_sell_block,
)
from csmarket.modules.sales.admin_payouts import (
    cancel_rolled_back,
    list_payouts,
    mark_paid,
    payout_detail,
    reject,
    reveal,
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
    CancelIn,
    PaidIn,
    PayoutDetailOut,
    PayoutsPageOut,
    RejectIn,
    ResolveIn,
    RevealIn,
    RevealOut,
    SaleSettingsOut,
    SellBlockIn,
    SellBlockOut,
    SellBlocksOut,
)
from csmarket.modules.sales.rules import SaleSettings
from csmarket.modules.sales.schemas import PayoutStatusOut, SaleStatusOut
from csmarket.modules.users.api import User

router = APIRouter(prefix="/admin/sales", tags=["admin"], dependencies=[Depends(require_admin)])

Db = Annotated[AsyncSession, Depends(db_session)]
Admin = Annotated[User, Depends(require_admin)]
Key = Annotated[str, Depends(required_key)]


async def _finish(
    db: AsyncSession,
    rid: str,
    *,
    scope: str,
    key: str,
    request: dict[str, Any],  # the shape `remember` takes
) -> PayoutDetailOut:
    detail = await payout_detail(db, rid)
    await remember(
        db, scope=scope, key=key, request=request, response=detail.model_dump(mode="json")
    )
    await db.commit()
    return detail


@router.get("/payouts", response_model=PayoutsPageOut, summary="Card payout requests")
async def get_payouts(
    db: Db,
    status: PayoutStatusOut = "to_pay",
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> PayoutsPageOut:
    """One status tab (``to_pay`` by default), newest first, with every tab's count."""
    return await list_payouts(db, status=status, cursor=cursor, limit=limit)


@router.get("/payouts/{request_id}", response_model=PayoutDetailOut, summary="A payout request")
async def get_payout(request_id: uuid.UUID, db: Db) -> PayoutDetailOut:
    """The request, its sale, the seller's history; the card masked."""
    return await payout_detail(db, str(request_id))


@router.post("/payouts/{request_id}/reveal", response_model=RevealOut, summary="The card number")
async def post_reveal(request_id: uuid.UUID, body: RevealIn, admin: Admin, db: Db) -> RevealOut:
    """The full card number to pay by hand; audited ``sales.card.show`` / ``sales.card.copy``.

    Keyless on purpose: it changes nothing but the audit trail, every reveal is its own audit
    row, and storing a replay would store the number.
    """
    number = await reveal(db, request_id=str(request_id), admin_id=admin.id, purpose=body.purpose)
    await db.commit()
    return RevealOut(number=number)


@router.post(
    "/payouts/{request_id}/paid",
    response_model=PayoutDetailOut,
    responses={409: {"description": "`payout_not_payable` or `idempotency_mismatch`"}},
    summary="Mark a payout paid",
)
async def post_paid(
    request_id: uuid.UUID, body: PaidIn, admin: Admin, db: Db, key: Key
) -> PayoutDetailOut:
    """«Выплачено» (an optional note); the seller gets a letter."""
    rid, scope = str(request_id), "admin.sales.payout.paid"
    request = {"id": rid, "note": body.note}
    if (hit := await replayed(db, scope=scope, key=key, request=request)) is not None:
        return PayoutDetailOut.model_validate(hit)
    done = await mark_paid(db, request_id=rid, admin_id=admin.id, note=body.note)
    await record(
        db,
        actor_id=admin.id,
        action="sales.payout.paid",
        target_type="payout_request",
        target_id=rid,
        payload={"amount_uzs": int(done.amount_uzs)},
    )
    return await _finish(db, rid, scope=scope, key=key, request=request)


@router.post(
    "/payouts/{request_id}/reject",
    response_model=PayoutDetailOut,
    responses={409: {"description": "`payout_not_payable` or `idempotency_mismatch`"}},
    summary="Reject a payout to the balance",
)
async def post_reject(
    request_id: uuid.UUID, body: RejectIn, admin: Admin, db: Db, key: Key
) -> PayoutDetailOut:
    """«Отклонить» (a reason is required): the amount before the card fee goes to the balance."""
    rid, scope = str(request_id), "admin.sales.payout.reject"
    request = {"id": rid, "reason": body.reason}
    if (hit := await replayed(db, scope=scope, key=key, request=request)) is not None:
        return PayoutDetailOut.model_validate(hit)
    done = await reject(db, request_id=rid, admin_id=admin.id, reason=body.reason)
    await record(
        db,
        actor_id=admin.id,
        action="sales.payout.reject",
        target_type="payout_request",
        target_id=rid,
        payload={"amount_uzs": int(done.amount_uzs + done.fee_uzs)},
    )
    return await _finish(db, rid, scope=scope, key=key, request=request)


@router.post(
    "/payouts/{request_id}/cancel",
    response_model=PayoutDetailOut,
    responses={
        409: {
            "description": "`payout_not_payable`, `payout_not_cancelable` (the sale was not "
            "reverted after it became payable) or `idempotency_mismatch`"
        }
    },
    summary="Cancel a payout whose sale was reverted",
)
async def post_cancel(
    request_id: uuid.UUID, body: CancelIn, admin: Admin, db: Db, key: Key
) -> PayoutDetailOut:
    """«Отменить (откат)» (a reason is required): only a ``to_pay`` request whose sale
    Skinslink reverted afterwards (``rolled_back``); nothing is paid, the sale becomes
    ``reverted`` and its attention is marked checked. If the money already went out, press
    «Выплачено» instead."""
    rid, scope = str(request_id), "admin.sales.payout.cancel"
    request = {"id": rid, "reason": body.reason}
    if (hit := await replayed(db, scope=scope, key=key, request=request)) is not None:
        return PayoutDetailOut.model_validate(hit)
    done = await cancel_rolled_back(db, request_id=rid, admin_id=admin.id, reason=body.reason)
    await record(
        db,
        actor_id=admin.id,
        action="sales.payout.cancel",
        target_type="payout_request",
        target_id=rid,
        payload={"amount_uzs": int(done.amount_uzs)},
    )
    return await _finish(db, rid, scope=scope, key=key, request=request)


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


@router.put("/settings", response_model=SaleSettingsOut, summary="Save the sale settings")
async def put_sale_settings(body: SaleSettings, admin: Admin, db: Db, key: Key) -> SaleSettingsOut:
    """Replace the document; new sales use it, existing ones keep their numbers. ``warnings``
    name what loses money; they never refuse the save."""
    scope, request = "admin.sales.settings", body.model_dump(mode="json")
    if (hit := await replayed(db, scope=scope, key=key, request=request)) is not None:
        return SaleSettingsOut.model_validate(hit)
    await save_settings(db, doc=body, admin_id=admin.id)
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
