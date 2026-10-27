"""``/api/v1/referrals*`` — the link visit and, for a partner, its own numbers."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.api.v1.deps import db_session
from csmarket.core.client_ip import client_ip
from csmarket.core.config import get_settings
from csmarket.modules.auth.api import guard_ip
from csmarket.modules.referrals.models import REF_COOKIE, REF_MAX_AGE
from csmarket.modules.referrals.visits import count_visit, earning_partner

router = APIRouter(prefix="/referrals", tags=["referrals"])

Db = Annotated[AsyncSession, Depends(db_session, scope="function")]


class VisitIn(BaseModel):
    """The code from a link's ``?ref=``."""

    code: str = Field(max_length=64)


@router.post(
    "/visit",
    status_code=204,
    responses={429: {"description": "Too many visits from this address"}},
    summary="Remember a partner's link",
)
async def post_visit(body: VisitIn, request: Request, db: Db) -> Response:
    """Count a visit by a partner's link and remember the link for 30 days (``csm_ref``).

    Keyless on purpose: it only moves a counter (once per visitor per day) and sets a
    cookie; a repeat changes nothing. An unknown or switched-off code answers the same 204
    and sets nothing.
    """
    await guard_ip(request, bucket="referral-visit")
    response = Response(status_code=204)
    partner = await earning_partner(db, body.code)
    if partner is None:
        return response
    await count_visit(db, partner, ip=client_ip(request))
    response.set_cookie(
        REF_COOKIE,
        partner.code,
        max_age=REF_MAX_AGE,
        httponly=True,
        secure=get_settings().is_prod,
        samesite="lax",
    )
    return response
