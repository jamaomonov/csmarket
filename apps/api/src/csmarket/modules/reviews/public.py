"""The public page's reviews: published (``rating >= 4 AND NOT hidden``) and by an account
that still exists, the visitor's locale first, newest first, 20 a page."""

from __future__ import annotations

from sqlalchemy import and_, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from csmarket.modules.orders.api import Order
from csmarket.modules.reviews.cursor import after, decode_rank_cursor, encode_rank_cursor
from csmarket.modules.reviews.models import Review, published
from csmarket.modules.reviews.schemas import PublicReviewOut, PublicReviewsOut
from csmarket.modules.reviews.settings_store import reviews_public
from csmarket.modules.users.api import User

PAGE = 20
_OFF = PublicReviewsOut(enabled=False, count=0, items=[], next_cursor=None)


def visible() -> ColumnElement[bool]:
    """Published, and its author's account was not deleted."""
    return and_(published(), User.deleted_at.is_(None))


async def published_count(db: AsyncSession) -> int:
    """How many reviews the page shows once it is on."""
    q = select(func.count()).select_from(Review).join(User, User.id == Review.user_id)
    return int(await db.scalar(q.where(visible())) or 0)


async def public_page(db: AsyncSession, *, locale: str, cursor: str | None) -> PublicReviewsOut:
    """Off: :data:`_OFF`. On: the count of what is shown and one page — no average: only
    4–5★ reviews are published, so it would always read 4+ (owner ruling 2026-10-23)."""
    if not await reviews_public(db):
        return _OFF
    count = await published_count(db)
    rank = case((Review.locale == locale, 0), else_=1)
    q = (
        select(Review, User.display_name, User.avatar_url, Order.market_hash_name, rank)
        .join(User, User.id == Review.user_id)
        .outerjoin(Order, Order.id == Review.order_id)
        .where(visible())
    )
    if cursor is not None:
        q = q.where(after(rank, Review.created_at, Review.id, decode_rank_cursor(cursor)))
    q = q.order_by(rank, Review.created_at.desc(), Review.id.desc()).limit(PAGE + 1)
    rows = (await db.execute(q)).all()
    more = len(rows) > PAGE
    rows = rows[:PAGE]
    items = [
        PublicReviewOut(
            id=review.id,
            author_name=name,
            author_avatar_url=avatar,
            rating=review.rating,
            text=review.text,
            kind=review.kind,
            skin_name=skin,
            locale=review.locale,
            created_at=review.created_at,
        )
        for review, name, avatar, skin, _ in rows
    ]
    last = rows[-1] if more else None
    return PublicReviewsOut(
        enabled=True,
        count=count,
        items=items,
        next_cursor=(
            encode_rank_cursor(int(last[4]), last[0].created_at, last[0].id) if last else None
        ),
    )


__all__ = ["PAGE", "public_page", "published_count", "visible"]
