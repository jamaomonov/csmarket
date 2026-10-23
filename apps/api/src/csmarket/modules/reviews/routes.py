"""``/api/v1/reviews*`` — a user's reviews of their deals (spec 2026-10-23-reviews).

Routers parse and dispatch: the rule is :mod:`.deals`, the writes :mod:`.service`. Every write
takes an ``Idempotency-Key``; the replay scope carries the user (``reviews.<verb>:<user id>``),
so the key itself stays within ``idempotent_responses.idempotency_key``'s 160 characters.
"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, Path, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.api.v1.deps import db_session
from csmarket.core.clock import now
from csmarket.core.idempotency import IDEMPOTENCY_HEADER, require_idempotency_key
from csmarket.modules.admin.api import remember, replayed
from csmarket.modules.auth.api import current_user, guard_ip
from csmarket.modules.reviews import service
from csmarket.modules.reviews.deals import Kind
from csmarket.modules.reviews.public import public_page
from csmarket.modules.reviews.schemas import (
    DealReviewOut,
    LocaleIn,
    PublicReviewsOut,
    ReviewIn,
    ReviewPendingOut,
)
from csmarket.modules.users.api import User

router = APIRouter(tags=["reviews"])

Db = Annotated[AsyncSession, Depends(db_session, scope="function")]
Me = Annotated[User, Depends(current_user)]
Number = Annotated[str, Path(min_length=1, max_length=8)]
Key = Annotated[str | None, Header(alias=IDEMPOTENCY_HEADER)]
_DEAL_ERRORS: dict[int | str, dict[str, str]] = {
    404: {"description": "`deal_not_found` — no such deal of mine"},
    409: {"description": "`review_not_allowed` or `idempotency_mismatch`"},
}


@router.get("/reviews/pending", response_model=ReviewPendingOut, summary="The deal to review now")
async def get_pending(user: Me, db: Db) -> ReviewPendingOut:
    """The newest deal of mine to review now (reviewable, within 14 days, no review, not
    snoozed or dismissed), or ``{"deal": null}``. Reads only."""
    return await service.pending(db, user_id=user.id, at=now())


@router.get(
    "/reviews/{kind}/{number}",
    response_model=DealReviewOut,
    responses={404: _DEAL_ERRORS[404]},
    summary="My review of a deal",
)
async def get_deal_review(kind: Kind, number: Number, user: Me, db: Db) -> DealReviewOut:
    """Whether I may review the deal now (``can_review``, ``editable_until``) and my review."""
    return await service.deal_review(db, user_id=user.id, kind=kind, number=number, at=now())


@router.put(
    "/reviews/{kind}/{number}",
    response_model=DealReviewOut,
    responses={**_DEAL_ERRORS, 429: {"description": "rate-limited (`review` bucket)"}},
    summary="Write or edit my review",
)
async def put_review(
    *,
    kind: Kind,
    number: Number,
    body: ReviewIn,
    request: Request,
    user: Me,
    db: Db,
    idempotency_key: Key = None,
) -> DealReviewOut:
    """1–5 stars, an optional text (≤ 1000 after trimming) and the interface locale.

    ``Idempotency-Key`` (16..160) is required; a replay answers the stored review, a key reused
    for another body is 409 ``idempotency_mismatch``.
    """
    key = require_idempotency_key(idempotency_key)
    user_id = user.id
    await guard_ip(request, bucket="review", subject=user_id)
    scope = f"reviews.put:{user_id}"
    asked: dict[str, object] = {"kind": kind, "number": number, **body.model_dump()}
    if (hit := await replayed(db, scope=scope, key=key, request=asked)) is not None:
        return DealReviewOut.model_validate(hit)
    out = await service.save_review(
        db, user_id=user_id, kind=kind, number=number, body=body, at=now()
    )
    await remember(db, scope=scope, key=key, request=asked, response=out.model_dump(mode="json"))
    await db.commit()
    return out


async def _answer(
    db: AsyncSession,
    *,
    verb: Literal["snooze", "dismiss"],
    user_id: str,
    kind: Kind,
    number: str,
    key: str,
) -> Response:
    scope = f"reviews.{verb}:{user_id}"
    asked: dict[str, object] = {"kind": kind, "number": number}
    if await replayed(db, scope=scope, key=key, request=asked) is None:
        act = service.snooze if verb == "snooze" else service.dismiss
        await act(db, user_id=user_id, kind=kind, number=number, at=now())
        await remember(db, scope=scope, key=key, request=asked, response={})
        await db.commit()
    return Response(status_code=204)


@router.post(
    "/reviews/{kind}/{number}/snooze",
    status_code=204,
    responses=_DEAL_ERRORS,
    summary="«Не сейчас»: ask again in 3 days",
)
async def post_snooze(
    kind: Kind, number: Number, user: Me, db: Db, idempotency_key: Key = None
) -> Response:
    """No prompt for this deal for 3 days. ``Idempotency-Key`` required; a replay is 204."""
    key = require_idempotency_key(idempotency_key)
    return await _answer(db, verb="snooze", user_id=user.id, kind=kind, number=number, key=key)


@router.post(
    "/reviews/{kind}/{number}/dismiss",
    status_code=204,
    responses=_DEAL_ERRORS,
    summary="×: never ask about this deal again",
)
async def post_dismiss(
    kind: Kind, number: Number, user: Me, db: Db, idempotency_key: Key = None
) -> Response:
    """No prompt for this deal again. ``Idempotency-Key`` required; a replay is 204."""
    key = require_idempotency_key(idempotency_key)
    return await _answer(db, verb="dismiss", user_id=user.id, kind=kind, number=number, key=key)


@router.get("/reviews", response_model=PublicReviewsOut, summary="Published reviews")
async def get_reviews(
    db: Db,
    locale: Annotated[LocaleIn, Query()] = "ru",
    cursor: Annotated[str | None, Query(max_length=200)] = None,
) -> PublicReviewsOut:
    """Public, no sign-in. While the page is off: ``enabled: false`` and nothing else (200, so
    the storefront shows «Скоро»). On: the count of the published reviews and 20 of them,
    ``locale``'s first, newest first. Never a Steam ID, an email, a number or an amount."""
    return await public_page(db, locale=locale, cursor=cursor)
