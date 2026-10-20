"""``/api/v1/admin/payments/settings`` — «Настройки оплаты»: the kassa fees the buyer pays on top
(spec 2026-10-14-kassa-fee).

Admin only. A save requires an ``Idempotency-Key`` (replay lookup → save → audit → replay row →
commit; the same key on another body is 409 ``idempotency_mismatch``) and carries ``If-Match``
(the ``updated_at`` it was edited from, or ``none``): a stale tab gets 409 ``settings_stale``.
Mounted before the admin payments router: its ``/{number}`` must not read ``settings``.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.api.v1.deps import db_session
from csmarket.modules.admin.api import remember, replayed, require_admin, required_key
from csmarket.modules.payments.fees import KassaFees
from csmarket.modules.payments.settings_admin import (
    PaymentSettingsOut,
    save_settings,
    settings_view,
)
from csmarket.modules.users.api import User

router = APIRouter(prefix="/admin/payments", tags=["admin"], dependencies=[Depends(require_admin)])

Db = Annotated[AsyncSession, Depends(db_session, scope="function")]
Admin = Annotated[User, Depends(require_admin)]
Key = Annotated[str, Depends(required_key)]


@router.get("/settings", response_model=PaymentSettingsOut, summary="The kassa fees")
async def get_payment_settings(db: Db) -> PaymentSettingsOut:
    """The percent per kassa, who saved it and when."""
    return await settings_view(db)


@router.put(
    "/settings",
    response_model=PaymentSettingsOut,
    responses={409: {"description": "`settings_stale` or `idempotency_mismatch`"}},
    summary="Save the kassa fees",
)
async def put_payment_settings(
    body: KassaFees,
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
) -> PaymentSettingsOut:
    """Replace the percents; new payments use them, open ones keep the fee they were shown."""
    scope, request = "admin.payments.settings", body.model_dump(mode="json")
    if (hit := await replayed(db, scope=scope, key=key, request=request)) is not None:
        return PaymentSettingsOut.model_validate(hit)
    await save_settings(db, fees=body, admin_id=admin.id, expected=if_match)
    out = await settings_view(db)
    await remember(db, scope=scope, key=key, request=request, response=out.model_dump(mode="json"))
    await db.commit()
    return out
