"""``/api/v1/admin/reviews*`` — the admin's «Отзывы» (spec 2026-10-23-reviews «Admin»).

Writes take ``Idempotency-Key`` (``required_key``) and replay with ``replayed`` / ``remember``.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.api.v1.deps import db_session
from csmarket.modules.admin.api import remember, replayed, require_admin, required_key
from csmarket.modules.reviews import admin
from csmarket.modules.reviews.deals import Kind
from csmarket.modules.reviews.schemas import (
    AdminReviewOut,
    AdminReviewsPage,
    LocaleIn,
    ReviewResolveIn,
    ReviewSettingsIn,
    ReviewSettingsOut,
)
from csmarket.modules.users.api import User

router = APIRouter(prefix="/admin/reviews", tags=["admin"], dependencies=[Depends(require_admin)])

Db = Annotated[AsyncSession, Depends(db_session, scope="function")]
Admin = Annotated[User, Depends(require_admin)]
Key = Annotated[str, Depends(required_key)]
_ONE: dict[int | str, dict[str, str]] = {
    404: {"description": "`review_not_found`"},
    409: {"description": "`review_not_bad` or `idempotency_mismatch`"},
}


@router.get("", response_model=AdminReviewsPage, summary="Reviews")
async def get_reviews(
    db: Db,
    tab: admin.Tab = "bad",
    kind: Kind | None = None,
    locale: LocaleIn | None = None,
    cursor: Annotated[str | None, Query(max_length=200)] = None,
) -> AdminReviewsPage:
    """«Плохие» (unresolved first), «Все» or «Хорошие»; ``kind`` and ``locale`` filter;
    ``bad_open`` counts the unresolved bad ones whatever the filters."""
    return await admin.list_reviews(db, tab=tab, kind=kind, locale=locale, cursor=cursor)


@router.get("/settings", response_model=ReviewSettingsOut, summary="The public-page switch")
async def get_settings(db: Db) -> ReviewSettingsOut:
    """Whether ``/reviews`` shows the published reviews, and how many it would show."""
    return await admin.settings_view(db)


@router.put(
    "/settings",
    response_model=ReviewSettingsOut,
    responses={409: {"description": "`idempotency_mismatch`"}},
    summary="Switch the public page",
)
async def put_settings(body: ReviewSettingsIn, user: Admin, db: Db, key: Key) -> ReviewSettingsOut:
    """«Показывать отзывы на сайте»; audited ``reviews.settings.save`` when it changes."""
    asked: dict[str, object] = body.model_dump()
    scope = "admin.reviews.settings"
    if (hit := await replayed(db, scope=scope, key=key, request=asked)) is not None:
        return ReviewSettingsOut.model_validate(hit)
    out = await admin.save_settings(db, value=body.reviews_public, admin_id=user.id)
    await remember(db, scope=scope, key=key, request=asked, response=out.model_dump(mode="json"))
    await db.commit()
    return out


async def _one(
    db: AsyncSession,
    *,
    scope: str,
    key: str,
    asked: dict[str, object],
    run: Callable[[], Awaitable[AdminReviewOut]],
) -> AdminReviewOut:
    if (hit := await replayed(db, scope=scope, key=key, request=asked)) is not None:
        return AdminReviewOut.model_validate(hit)
    out = await run()
    await remember(db, scope=scope, key=key, request=asked, response=out.model_dump(mode="json"))
    await db.commit()
    return out


@router.post(
    "/{review_id}/resolve", response_model=AdminReviewOut, responses=_ONE, summary="«Разобрано»"
)
async def post_resolve(
    review_id: str, body: ReviewResolveIn, user: Admin, db: Db, key: Key
) -> AdminReviewOut:
    """Mark a bad review handled with a note; one already resolved stays as it was."""
    return await _one(
        db,
        scope="admin.reviews.resolve",
        key=key,
        asked={"review_id": review_id, "note": body.note},
        run=lambda: admin.resolve(db, review_id=review_id, admin_id=user.id, note=body.note),
    )


@router.post(
    "/{review_id}/hide", response_model=AdminReviewOut, responses=_ONE, summary="Hide from the site"
)
async def post_hide(review_id: str, user: Admin, db: Db, key: Key) -> AdminReviewOut:
    """«Скрыть с сайта»."""
    return await _one(
        db,
        scope="admin.reviews.hide",
        key=key,
        asked={"review_id": review_id},
        run=lambda: admin.set_hidden(db, review_id=review_id, admin_id=user.id, hidden=True),
    )


@router.post(
    "/{review_id}/unhide", response_model=AdminReviewOut, responses=_ONE, summary="Show on the site"
)
async def post_unhide(review_id: str, user: Admin, db: Db, key: Key) -> AdminReviewOut:
    """«Показать»."""
    return await _one(
        db,
        scope="admin.reviews.unhide",
        key=key,
        asked={"review_id": review_id},
        run=lambda: admin.set_hidden(db, review_id=review_id, admin_id=user.id, hidden=False),
    )
