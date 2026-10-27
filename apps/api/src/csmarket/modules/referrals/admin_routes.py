"""``/api/v1/admin/referrals*`` — the admin's «Партнёры» (spec 2026-10-27-referrals «Admin»).

Writes take ``Idempotency-Key`` (``required_key``) and replay with ``replayed`` / ``remember``.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.api.v1.deps import db_session
from csmarket.modules.admin.api import remember, replayed, require_admin, required_key
from csmarket.modules.referrals import partners
from csmarket.modules.referrals.schemas import (
    AdminPartnerDetailOut,
    AdminPartnerOut,
    AdminPartnersOut,
    PartnerIn,
    PartnerPatch,
    UserReferralOut,
)
from csmarket.modules.users.api import User

router = APIRouter(prefix="/admin/referrals", tags=["admin"], dependencies=[Depends(require_admin)])

Db = Annotated[AsyncSession, Depends(db_session, scope="function")]
Admin = Annotated[User, Depends(require_admin)]
Key = Annotated[str, Depends(required_key)]
_WRITE: dict[int | str, dict[str, str]] = {
    404: {"description": "`user_not_found` or `partner_not_found`"},
    409: {"description": "`partner_exists`, `code_taken`, `code_locked` or `idempotency_mismatch`"},
    422: {"description": "`code_invalid`, or the percent / term out of range"},
}


@router.get("/partners", response_model=AdminPartnersOut, summary="Partners")
async def get_partners(db: Db) -> AdminPartnersOut:
    """Every partner with its totals, most revenue brought first."""
    return AdminPartnersOut(items=await partners.list_partners(db))


@router.post(
    "/partners",
    response_model=AdminPartnerOut,
    status_code=201,
    responses=_WRITE,
    summary="Make an account a partner",
)
async def post_partner(body: PartnerIn, user: Admin, db: Db, key: Key) -> AdminPartnerOut:
    """«Сделать партнёром»; adds the ``partner`` role, audited ``referrals.partner.create``."""
    asked: dict[str, object] = body.model_dump(mode="json")
    scope = "admin.referrals.create"
    if (hit := await replayed(db, scope=scope, key=key, request=asked)) is not None:
        return AdminPartnerOut.model_validate(hit)
    out = await partners.create_partner(db, body=body, admin_id=user.id)
    await remember(db, scope=scope, key=key, request=asked, response=out.model_dump(mode="json"))
    await db.commit()
    return out


@router.patch(
    "/partners/{user_id}",
    response_model=AdminPartnerOut,
    responses=_WRITE,
    summary="Change a partner's terms",
)
async def patch_partner(
    user_id: str, body: PartnerPatch, user: Admin, db: Db, key: Key
) -> AdminPartnerOut:
    """Code (until someone came by it), percent, term, the switch, the note; audited
    ``referrals.partner.update``."""
    asked: dict[str, object] = {
        "user_id": user_id,
        **body.model_dump(mode="json", exclude_unset=True),
    }
    scope = "admin.referrals.update"
    if (hit := await replayed(db, scope=scope, key=key, request=asked)) is not None:
        return AdminPartnerOut.model_validate(hit)
    out = await partners.update_partner(db, user_id=user_id, patch=body, admin_id=user.id)
    await remember(db, scope=scope, key=key, request=asked, response=out.model_dump(mode="json"))
    await db.commit()
    return out


@router.get(
    "/partners/{user_id}",
    response_model=AdminPartnerDetailOut,
    responses={404: {"description": "`partner_not_found`"}, 422: {"description": "`cursor`"}},
    summary="A partner's page",
)
async def get_partner(
    user_id: str, db: Db, cursor: Annotated[str | None, Query(max_length=200)] = None
) -> AdminPartnerDetailOut:
    """Terms, totals, months and 50 rewards (with their orders) a page, newest first."""
    return await partners.detail(db, user_id=user_id, after=cursor)


@router.get("/users/{user_id}", response_model=UserReferralOut, summary="Who brought an account")
async def get_user_referral(user_id: str, db: Db) -> UserReferralOut:
    """The user card's line: the partner the account came by, and whether it is one."""
    return await partners.user_referral(db, user_id)
