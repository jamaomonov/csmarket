"""Admin routes: kassa limits («Лимит без проверки») and a user's risk policy.

Saves require an ``Idempotency-Key`` (replay lookup → save → audit → replay row → commit). The
limits' save also carries ``If-Match`` (the newest ``updated_at``, or ``none``): a stale tab gets
409 ``settings_stale``. The limits router is mounted before the admin payments router, whose
``/{number}`` must not read ``review-limits``.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.api.v1.deps import db_session
from csmarket.modules.admin.api import remember, replayed, require_admin, required_key
from csmarket.modules.admin.users_service import get_user
from csmarket.modules.risk.limits import limits_view, save_limits
from csmarket.modules.risk.policy import policy_view, save_policy
from csmarket.modules.risk.schemas import (
    ReviewLimitsIn,
    ReviewLimitsOut,
    RiskPolicyIn,
    RiskPolicyOut,
)
from csmarket.modules.users.api import User

limits_router = APIRouter(
    prefix="/admin/payments/review-limits", tags=["admin"], dependencies=[Depends(require_admin)]
)
policy_router = APIRouter(
    prefix="/admin/users", tags=["admin"], dependencies=[Depends(require_admin)]
)
Db = Annotated[AsyncSession, Depends(db_session, scope="function")]
Admin = Annotated[User, Depends(require_admin)]
Key = Annotated[str, Depends(required_key)]


@limits_router.get("", response_model=ReviewLimitsOut, summary="The kassa limits")
async def get_limits(db: Db) -> ReviewLimitsOut:
    """Every kassa's limit, who saved last and when."""
    return await limits_view(db)


@limits_router.put(
    "",
    response_model=ReviewLimitsOut,
    responses={409: {"description": "`settings_stale` or `idempotency_mismatch`"}},
    summary="Save the kassa limits",
)
async def put_limits(
    body: ReviewLimitsIn,
    admin: Admin,
    db: Db,
    key: Key,
    if_match: Annotated[
        str | None,
        Header(
            alias="If-Match",
            max_length=64,
            description="The `updated_at` the edit started from, or `none`. Absent: no check.",
        ),
    ] = None,
) -> ReviewLimitsOut:
    """Replace the given kassas' limits; payments already held stay held."""
    scope, request = "admin.payments.review_limits", body.model_dump(mode="json")
    if (hit := await replayed(db, scope=scope, key=key, request=request)) is not None:
        return ReviewLimitsOut.model_validate(hit)
    await save_limits(db, body=body, admin_id=admin.id, expected=if_match)
    out = await limits_view(db)
    await remember(db, scope=scope, key=key, request=request, response=out.model_dump(mode="json"))
    await db.commit()
    return out


@policy_router.get("/{user_id}/risk", response_model=RiskPolicyOut, summary="A user's risk policy")
async def get_policy(user_id: str, db: Db) -> RiskPolicyOut:
    """The policy (defaults when none), the user's kassa money and open holds."""
    user = await get_user(db, user_id)
    return await policy_view(db, user.id)


@policy_router.put(
    "/{user_id}/risk", response_model=RiskPolicyOut, summary="Save a user's risk policy"
)
async def put_policy(
    user_id: str, body: RiskPolicyIn, admin: Admin, db: Db, key: Key
) -> RiskPolicyOut:
    """Replace the user's trusted / blocked flags, own limit and note."""
    user = await get_user(db, user_id)
    scope, request = "admin.users.risk", {"user_id": user.id, **body.model_dump(mode="json")}
    if (hit := await replayed(db, scope=scope, key=key, request=request)) is not None:
        return RiskPolicyOut.model_validate(hit)
    await save_policy(db, user_id=user.id, body=body, admin_id=admin.id)
    out = await policy_view(db, user.id)
    await remember(db, scope=scope, key=key, request=request, response=out.model_dump(mode="json"))
    await db.commit()
    return out
