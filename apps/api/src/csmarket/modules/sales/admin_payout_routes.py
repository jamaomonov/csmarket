"""``/api/v1/admin/sales/payouts*`` — «Заявки на выплату» (spec 2026-10-08 §7; admin review
2026-10-12 H1, H2, H3, M1, M5, M10).

Admin only. Every write requires an ``Idempotency-Key`` (16..160): replay lookup → the change
(:mod:`.admin_payouts`, :mod:`.admin_undo`) → audit → replay row → commit; the same key on
another body is 409 ``idempotency_mismatch``. The reveal is keyless on purpose: what it
changes besides its own audit row is a claim, which is idempotent by itself, and a replay
would have to store the card number.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.api.v1.deps import db_session
from csmarket.modules.admin.api import record, remember, replayed, require_admin, required_key
from csmarket.modules.sales.admin_payouts import (
    cancel_rolled_back,
    claim,
    list_payouts,
    mark_paid,
    payout_detail,
    reject,
    release,
    reveal,
)
from csmarket.modules.sales.admin_schemas import (
    CancelIn,
    ClaimIn,
    PaidIn,
    PayoutDetailOut,
    PayoutsPageOut,
    PayoutTab,
    RejectIn,
    RevealIn,
    RevealOut,
    UndoIn,
)
from csmarket.modules.sales.admin_undo import undo
from csmarket.modules.users.api import User

router = APIRouter(
    prefix="/admin/sales/payouts", tags=["admin"], dependencies=[Depends(require_admin)]
)

Db = Annotated[AsyncSession, Depends(db_session)]
Admin = Annotated[User, Depends(require_admin)]
Key = Annotated[str, Depends(required_key)]

_CLAIMED = "`payout_claimed` (another admin is paying it)"


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


async def _audit(db: AsyncSession, admin: User, action: str, rid: str, **payload: Any) -> None:
    await record(
        db,
        actor_id=admin.id,
        action=action,
        target_type="payout_request",
        target_id=rid,
        payload=payload,
    )


@router.get("", response_model=PayoutsPageOut, summary="Card payout requests")
async def get_payouts(
    db: Db,
    status: PayoutTab = "to_pay",
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    q: Annotated[str | None, Query(max_length=64)] = None,
) -> PayoutsPageOut:
    """One status tab (``to_pay`` by default, oldest first; the others newest first; ``all``
    every status) with every tab's count and the day's totals. ``q``: a sale-number prefix,
    the card's last four, a name substring or a Steam ID."""
    return await list_payouts(db, status=status, cursor=cursor, limit=limit, q=q)


@router.get("/{request_id}", response_model=PayoutDetailOut, summary="A payout request")
async def get_payout(request_id: uuid.UUID, db: Db) -> PayoutDetailOut:
    """The request, its sale, the risks, the seller's history; the card masked."""
    return await payout_detail(db, str(request_id))


@router.post(
    "/{request_id}/reveal",
    response_model=RevealOut,
    responses={409: {"description": f"`payout_not_payable` or {_CLAIMED}"}},
    summary="The card number",
)
async def post_reveal(request_id: uuid.UUID, body: RevealIn, admin: Admin, db: Db) -> RevealOut:
    """The full card number to pay by hand, for a ``to_pay`` request only; audited
    ``sales.card.show`` / ``sales.card.copy``, and the request is claimed for the admin.

    Keyless on purpose: the claim is idempotent by itself, every reveal is its own audit row,
    and storing a replay would store the number.
    """
    number = await reveal(db, request_id=str(request_id), admin_id=admin.id, purpose=body.purpose)
    await db.commit()
    return RevealOut(number=number)


@router.post(
    "/{request_id}/claim",
    response_model=PayoutDetailOut,
    responses={409: {"description": f"`payout_not_payable`, {_CLAIMED}, `idempotency_mismatch`"}},
    summary="Take a payout to pay it",
)
async def post_claim(
    request_id: uuid.UUID, body: ClaimIn, admin: Admin, db: Db, key: Key
) -> PayoutDetailOut:
    """«Беру в работу»: the request is the admin's for 15 minutes (renewed by another claim or
    a reveal); ``takeover`` takes it from another admin (audited ``sales.payout.takeover``)."""
    rid, scope = str(request_id), "admin.sales.payout.claim"
    request = {"id": rid, "takeover": body.takeover}
    if (hit := await replayed(db, scope=scope, key=key, request=request)) is not None:
        return PayoutDetailOut.model_validate(hit)
    await claim(db, request_id=rid, admin_id=admin.id, takeover=body.takeover)
    return await _finish(db, rid, scope=scope, key=key, request=request)


@router.post(
    "/{request_id}/release",
    response_model=PayoutDetailOut,
    responses={409: {"description": f"{_CLAIMED} or `idempotency_mismatch`"}},
    summary="Give a claimed payout back",
)
async def post_release(request_id: uuid.UUID, admin: Admin, db: Db, key: Key) -> PayoutDetailOut:
    """«Отпустить»: the claimer gives the request back (audited ``sales.payout.release``)."""
    rid, scope = str(request_id), "admin.sales.payout.release"
    request = {"id": rid}
    if (hit := await replayed(db, scope=scope, key=key, request=request)) is not None:
        return PayoutDetailOut.model_validate(hit)
    await release(db, request_id=rid, admin_id=admin.id)
    return await _finish(db, rid, scope=scope, key=key, request=request)


@router.post(
    "/{request_id}/paid",
    response_model=PayoutDetailOut,
    responses={
        409: {
            "description": f"`payout_not_payable`, {_CLAIMED}, `payout_user_blocked` (a banned "
            "account or a frozen wallet), `payout_sale_reverted` (the trade was reverted) — both "
            "need `override_reason` — or `idempotency_mismatch`"
        }
    },
    summary="Mark a payout paid",
)
async def post_paid(
    request_id: uuid.UUID, body: PaidIn, admin: Admin, db: Db, key: Key
) -> PayoutDetailOut:
    """«Выплачено» (an optional note); the seller gets a letter. A banned account or a frozen
    wallet needs ``override_reason`` (audited with the payment)."""
    rid, scope = str(request_id), "admin.sales.payout.paid"
    request = {"id": rid, "note": body.note, "override_reason": body.override_reason}
    if (hit := await replayed(db, scope=scope, key=key, request=request)) is not None:
        return PayoutDetailOut.model_validate(hit)
    done, overridden = await mark_paid(
        db, request_id=rid, admin_id=admin.id, note=body.note, override_reason=body.override_reason
    )
    extra = {"override": body.override_reason} if overridden else {}
    await _audit(db, admin, "sales.payout.paid", rid, amount_uzs=int(done.amount_uzs), **extra)
    return await _finish(db, rid, scope=scope, key=key, request=request)


@router.post(
    "/{request_id}/reject",
    response_model=PayoutDetailOut,
    responses={
        409: {
            "description": f"`payout_not_payable`, {_CLAIMED}, `wallet_frozen` or "
            "`idempotency_mismatch`"
        }
    },
    summary="Reject a payout to the balance",
)
async def post_reject(
    request_id: uuid.UUID, body: RejectIn, admin: Admin, db: Db, key: Key
) -> PayoutDetailOut:
    """«Отклонить» (a reason is required): the amount before the card fee goes to the balance.
    A frozen wallet cannot take it (409 ``wallet_frozen``)."""
    rid, scope = str(request_id), "admin.sales.payout.reject"
    request = {"id": rid, "reason": body.reason}
    if (hit := await replayed(db, scope=scope, key=key, request=request)) is not None:
        return PayoutDetailOut.model_validate(hit)
    done = await reject(db, request_id=rid, admin_id=admin.id, reason=body.reason)
    amount = int(done.amount_uzs + done.fee_uzs)
    await _audit(db, admin, "sales.payout.reject", rid, amount_uzs=amount)
    return await _finish(db, rid, scope=scope, key=key, request=request)


@router.post(
    "/{request_id}/undo",
    response_model=PayoutDetailOut,
    responses={
        409: {
            "description": f"`undo_expired`, `undo_not_yours`, `balance_spent`, `wallet_frozen`, {_CLAIMED} or "
            "`idempotency_mismatch`"
        }
    },
    summary="Undo a payout decided minutes ago",
)
async def post_undo(
    request_id: uuid.UUID, body: UndoIn, admin: Admin, db: Db, key: Key
) -> PayoutDetailOut:
    """«Вернуть в очередь» (a reason is required) within 10 minutes of «Выплачено» or
    «Отклонить». Undoing a rejection takes its credit back off the balance — refused when the
    balance no longer covers it (``balance_spent``). Audited ``sales.payout.undo``."""
    rid, scope = str(request_id), "admin.sales.payout.undo"
    request = {"id": rid, "reason": body.reason}
    if (hit := await replayed(db, scope=scope, key=key, request=request)) is not None:
        return PayoutDetailOut.model_validate(hit)
    done, was = await undo(db, request_id=rid, admin_id=admin.id)
    await _audit(
        db,
        admin,
        "sales.payout.undo",
        rid,
        was=was,
        reason=body.reason,
        amount_uzs=int(done.amount_uzs),
    )
    return await _finish(db, rid, scope=scope, key=key, request=request)


@router.post(
    "/{request_id}/cancel",
    response_model=PayoutDetailOut,
    responses={
        409: {
            "description": "`payout_not_payable`, `payout_not_cancelable` (the sale was not "
            f"reverted after it became payable), {_CLAIMED} or `idempotency_mismatch`"
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
    await _audit(db, admin, "sales.payout.cancel", rid, amount_uzs=int(done.amount_uzs))
    return await _finish(db, rid, scope=scope, key=key, request=request)


__all__ = ["router"]
