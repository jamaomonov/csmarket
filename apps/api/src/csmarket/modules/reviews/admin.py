"""The admin's «Отзывы»: the list by tab, «Разобрано», hide / show, the public-page switch.

Every write is audited in the caller's transaction (``reviews.review.resolve``,
``reviews.review.hide`` / ``unhide``, ``reviews.settings.save``). Payloads name the deal and
the stars, never the text or the note. Flushes, never commits.
"""

from __future__ import annotations

import uuid
from typing import Literal

from sqlalchemy import Integer, case, func, literal, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased
from sqlalchemy.sql.elements import ColumnElement

from csmarket.core.clock import now
from csmarket.core.errors import ConflictError, NotFoundError
from csmarket.core.logging import get_logger
from csmarket.modules.admin.api import record
from csmarket.modules.orders.api import Order
from csmarket.modules.reviews.cursor import after, decode_rank_cursor, encode_rank_cursor
from csmarket.modules.reviews.models import GOOD_FROM, Review, bad
from csmarket.modules.reviews.public import published_count
from csmarket.modules.reviews.schemas import (
    AdminReviewOut,
    AdminReviewsPage,
    ReviewAdminUserOut,
    ReviewSettingsOut,
)
from csmarket.modules.reviews.settings_store import save_reviews_public, settings_row
from csmarket.modules.sales.api import Sale
from csmarket.modules.users.api import User

Tab = Literal["bad", "all", "good"]
PAGE = 50

log = get_logger("csmarket.reviews.admin")


async def bad_open_count(db: AsyncSession) -> int:
    """Bad reviews no admin has resolved (the menu counter, the gauge)."""
    q = select(func.count()).select_from(Review).where(bad(), Review.resolved_at.is_(None))
    return int(await db.scalar(q) or 0)


def _person(user: User) -> ReviewAdminUserOut:
    return ReviewAdminUserOut(
        id=user.id, display_name=user.display_name, avatar_url=user.avatar_url
    )


def _item(review: Review, number: str, author: User, admin: User | None) -> AdminReviewOut:
    return AdminReviewOut(
        id=review.id,
        kind=review.kind,
        number=number,
        rating=review.rating,
        text=review.text,
        locale=review.locale,
        hidden=review.hidden,
        published=review.rating >= GOOD_FROM and not review.hidden,
        user=_person(author),
        created_at=review.created_at,
        updated_at=review.updated_at,
        resolved_at=review.resolved_at,
        resolved_by=_person(admin) if admin is not None else None,
        resolved_note=review.resolved_note,
    )


def _rank(tab: Tab) -> ColumnElement[int]:
    """«Плохие» puts the unresolved first; the other tabs are one group."""
    if tab == "bad":
        return case((Review.resolved_at.is_(None), 0), else_=1)
    return literal(0, Integer)


def _filters(tab: Tab, kind: str | None, locale: str | None) -> list[ColumnElement[bool]]:
    found: list[ColumnElement[bool]] = []
    if tab == "bad":
        found.append(bad())
    elif tab == "good":
        found.append(Review.rating >= GOOD_FROM)
    if kind is not None:
        found.append(Review.kind == kind)
    if locale is not None:
        found.append(Review.locale == locale)
    return found


async def list_reviews(
    db: AsyncSession, *, tab: Tab, kind: str | None, locale: str | None, cursor: str | None
) -> AdminReviewsPage:
    """One page of a tab, newest first within its groups, :data:`PAGE` a page."""
    author, admin = aliased(User), aliased(User)
    rank = _rank(tab)
    q = (
        select(Review, func.coalesce(Order.number, Sale.number), author, admin, rank)
        .join(author, author.id == Review.user_id)
        .outerjoin(admin, admin.id == Review.resolved_by)
        .outerjoin(Order, Order.id == Review.order_id)
        .outerjoin(Sale, Sale.id == Review.sale_id)
        .where(*_filters(tab, kind, locale))
    )
    if cursor is not None:
        q = q.where(after(rank, Review.created_at, Review.id, decode_rank_cursor(cursor)))
    q = q.order_by(rank, Review.created_at.desc(), Review.id.desc()).limit(PAGE + 1)
    rows = (await db.execute(q)).all()
    more = len(rows) > PAGE
    rows = rows[:PAGE]
    last = rows[-1] if more else None
    return AdminReviewsPage(
        items=[_item(r, n, a, m) for r, n, a, m, _ in rows],
        next_cursor=(
            encode_rank_cursor(int(last[4]), last[0].created_at, last[0].id) if last else None
        ),
        bad_open=await bad_open_count(db),
    )


async def _locked(db: AsyncSession, review_id: str) -> Review:
    """The review under a row lock; 404 ``review_not_found`` for a malformed or unknown id."""
    try:
        uuid.UUID(review_id)
    except ValueError:
        raise NotFoundError("no such review", code="review_not_found") from None
    review = await db.get(Review, review_id, with_for_update=True, populate_existing=True)
    if review is None:
        raise NotFoundError("no such review", code="review_not_found")
    return review


async def _number(db: AsyncSession, review: Review) -> str:
    if review.order_id is not None:
        return str(await db.scalar(select(Order.number).where(Order.id == review.order_id)))
    return str(await db.scalar(select(Sale.number).where(Sale.id == review.sale_id)))


async def _view(db: AsyncSession, review: Review) -> AdminReviewOut:
    author = await db.get_one(User, review.user_id)
    admin = await db.get(User, review.resolved_by) if review.resolved_by else None
    return _item(review, await _number(db, review), author, admin)


async def _audit(db: AsyncSession, review: Review, *, admin_id: str, action: str) -> None:
    await record(
        db,
        actor_id=admin_id,
        action=action,
        target_type="review",
        target_id=review.id,
        payload={"kind": review.kind, "number": await _number(db, review), "rating": review.rating},
    )


async def resolve(db: AsyncSession, *, review_id: str, admin_id: str, note: str) -> AdminReviewOut:
    """«Разобрано»: stamp a bad review handled, once; one already resolved is left as it is.

    Raises:
        NotFoundError: ``review_not_found``.
        ConflictError: ``review_not_bad`` — 4–5 stars need no handling.
    """
    review = await _locked(db, review_id)
    if review.rating >= GOOD_FROM:
        raise ConflictError("only a bad review is resolved", code="review_not_bad")
    if review.resolved_at is None:
        review.resolved_at, review.resolved_by, review.resolved_note = now(), admin_id, note
        await _audit(db, review, admin_id=admin_id, action="reviews.review.resolve")
        await db.flush()
        log.info("reviews.resolved", kind=review.kind, rating=review.rating)
    return await _view(db, review)


async def set_hidden(
    db: AsyncSession, *, review_id: str, admin_id: str, hidden: bool
) -> AdminReviewOut:
    """«Скрыть с сайта» / «Показать»; audited only when it changes. Raises 404."""
    review = await _locked(db, review_id)
    if review.hidden != hidden:
        review.hidden = hidden
        action = "reviews.review.hide" if hidden else "reviews.review.unhide"
        await _audit(db, review, admin_id=admin_id, action=action)
        await db.flush()
    return await _view(db, review)


async def settings_view(db: AsyncSession) -> ReviewSettingsOut:
    """The switch, the count it would show, who set it last."""
    row = await settings_row(db)
    admin = await db.get(User, row.updated_by) if row is not None and row.updated_by else None
    return ReviewSettingsOut(
        reviews_public=row is not None and row.reviews_public,
        published_count=await published_count(db),
        updated_at=row.updated_at if row is not None else None,
        updated_by=_person(admin) if admin is not None else None,
    )


async def save_settings(db: AsyncSession, *, value: bool, admin_id: str) -> ReviewSettingsOut:
    """Set the switch; audited when it changes."""
    row = await settings_row(db)
    was = row is not None and row.reviews_public
    await save_reviews_public(db, value=value, admin_id=admin_id)
    if was != value:
        await record(
            db,
            actor_id=admin_id,
            action="reviews.settings.save",
            target_type="review_settings",
            target_id="1",
            payload={"enabled": value},
        )
        await db.flush()
        log.info("reviews.settings.saved", enabled=value)
    return await settings_view(db)


__all__ = [
    "PAGE",
    "Tab",
    "bad_open_count",
    "list_reviews",
    "resolve",
    "save_settings",
    "set_hidden",
    "settings_view",
]
