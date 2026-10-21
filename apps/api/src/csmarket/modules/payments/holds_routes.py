"""``/api/v1/admin/payments/holds`` — «На проверке»: held kassa payments and the two decisions
(spec 2026-10-21-payment-risk-limits).

Admin only. A decision requires an ``Idempotency-Key`` (replay lookup → decide → audit → replay
row → commit; the same key on another hold is 409 ``idempotency_mismatch``). Mounted before the
admin payments router: its ``/{number}`` must not read ``holds``.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.api.v1.deps import db_session
from csmarket.modules.admin.api import remember, replayed, require_admin, required_key
from csmarket.modules.payments.holds_admin import (
    HoldOut,
    HoldPage,
    HoldState,
    list_holds,
    mark_returned,
    release,
)
from csmarket.modules.users.api import User

router = APIRouter(
    prefix="/admin/payments/holds", tags=["admin"], dependencies=[Depends(require_admin)]
)

Db = Annotated[AsyncSession, Depends(db_session, scope="function")]
Admin = Annotated[User, Depends(require_admin)]
Key = Annotated[str, Depends(required_key)]

_DECISION_ERRORS: dict[int | str, dict[str, str]] = {
    404: {"description": "`hold_not_found`"},
    409: {"description": "`hold_decided` or `idempotency_mismatch`"},
}


@router.get("", response_model=HoldPage, summary="Held kassa payments")
async def get_holds(
    db: Db,
    state: Annotated[HoldState, Query()] = "open",
    cursor: Annotated[str | None, Query(max_length=200)] = None,
) -> HoldPage:
    """Open holds newest first by when they were held, or decided ones by when decided."""
    return await list_holds(db, state=state, cursor=cursor)


@router.post(
    "/{hold_id}/release",
    response_model=HoldOut,
    responses=_DECISION_ERRORS,
    summary="Release a held payment",
)
async def post_release(hold_id: str, admin: Admin, db: Db, key: Key) -> HoldOut:
    """«Пропустить»: the order is paid and bought, the top-up credited."""
    scope, request = "admin.payments.hold.release", {"hold_id": hold_id}
    if (hit := await replayed(db, scope=scope, key=key, request=request)) is not None:
        return HoldOut.model_validate(hit)
    out = await release(db, hold_id=hold_id, admin_id=admin.id)
    await remember(db, scope=scope, key=key, request=request, response=out.model_dump(mode="json"))
    await db.commit()
    return out


@router.post(
    "/{hold_id}/returned",
    response_model=HoldOut,
    responses=_DECISION_ERRORS,
    summary="Record a held payment returned to the card",
)
async def post_returned(hold_id: str, admin: Admin, db: Db, key: Key) -> HoldOut:
    """«Вернул на карту»: nothing is credited; the order is cancelled, the top-up rejected."""
    scope, request = "admin.payments.hold.returned", {"hold_id": hold_id}
    if (hit := await replayed(db, scope=scope, key=key, request=request)) is not None:
        return HoldOut.model_validate(hit)
    out = await mark_returned(db, hold_id=hold_id, admin_id=admin.id)
    await remember(db, scope=scope, key=key, request=request, response=out.model_dump(mode="json"))
    await db.commit()
    return out
