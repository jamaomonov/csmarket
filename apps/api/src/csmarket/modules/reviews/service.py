"""A user's review of their own deal: write, read, and the prompt's «Не сейчас» / ×.

Every write locks the deal's row first (``find_deal(lock=True)``), so two first reviews of one
deal from two tabs queue up and the second edits the first. Flushes, never commits. Logs the
kind, number and rating only — never the text.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.errors import ConflictError, NotFoundError
from csmarket.core.logging import get_logger
from csmarket.core.metrics import record_review
from csmarket.modules.reviews.deals import (
    Deal,
    Kind,
    editable_until,
    find_deal,
    pending_for,
    reviewable,
)
from csmarket.modules.reviews.models import GOOD_FROM, SNOOZE, Review, ReviewPrompt
from csmarket.modules.reviews.schemas import (
    DealOut,
    DealReviewOut,
    MyReviewOut,
    ReviewIn,
    ReviewPendingOut,
)

log = get_logger("csmarket.reviews")


async def _owned(
    db: AsyncSession, user_id: str, kind: Kind, number: str, *, lock: bool = False
) -> Deal:
    """The deal if it is ``user_id``'s; 404 otherwise (another's deal reads as no deal)."""
    deal = await find_deal(db, kind, number, lock=lock)
    if deal is None or deal.user_id != user_id:
        raise NotFoundError("no such deal", code="deal_not_found")
    return deal


def _allowed(deal: Deal, at: datetime) -> None:
    """409 ``review_not_allowed`` outside rule 7 or the 14 days."""
    if not reviewable(deal, at):
        raise ConflictError("this deal cannot be reviewed now", code="review_not_allowed")


async def review_of(db: AsyncSession, deal: Deal) -> Review | None:
    """The deal's review, if written."""
    if deal.order_id is not None:
        return await db.scalar(select(Review).where(Review.order_id == deal.order_id))
    return await db.scalar(select(Review).where(Review.sale_id == deal.sale_id))


def _out(deal: Deal, review: Review | None, at: datetime) -> DealReviewOut:
    mine = (
        None
        if review is None
        else MyReviewOut(
            rating=review.rating,
            text=review.text,
            locale=review.locale,
            created_at=review.created_at,
            updated_at=review.updated_at,
        )
    )
    return DealReviewOut(
        kind=deal.kind,
        number=deal.number,
        can_review=reviewable(deal, at),
        editable_until=editable_until(deal),
        review=mine,
    )


async def deal_review(
    db: AsyncSession, *, user_id: str, kind: Kind, number: str, at: datetime
) -> DealReviewOut:
    """My deal and my review of it. Raises 404 ``deal_not_found``."""
    deal = await _owned(db, user_id, kind, number)
    return _out(deal, await review_of(db, deal), at)


def _edit(review: Review, body: ReviewIn, at: datetime) -> None:
    """Apply an edit. A changed review that is bad afterwards is reopened (unresolved): good →
    bad (spec), and a resolved bad review the user rewrote, so an admin sees it again."""
    changed = (review.rating, review.text) != (body.rating, body.text)
    if changed and body.rating < GOOD_FROM:
        review.resolved_at = review.resolved_by = review.resolved_note = None
    review.rating, review.text, review.locale = body.rating, body.text, body.locale
    review.updated_at = at


async def save_review(
    db: AsyncSession, *, user_id: str, kind: Kind, number: str, body: ReviewIn, at: datetime
) -> DealReviewOut:
    """Write or edit my review of my deal. Flushes.

    Raises:
        NotFoundError: ``deal_not_found``.
        ConflictError: ``review_not_allowed``.
    """
    deal = await _owned(db, user_id, kind, number, lock=True)
    _allowed(deal, at)
    review = await review_of(db, deal)
    if review is None:
        review = Review(
            kind=deal.kind,
            order_id=deal.order_id,
            sale_id=deal.sale_id,
            user_id=user_id,
            rating=body.rating,
            text=body.text,
            locale=body.locale,
            created_at=at,
            updated_at=at,
        )
        db.add(review)
        record_review(deal.kind, body.rating)
    else:
        _edit(review, body, at)
    await db.flush()
    log.info("reviews.saved", kind=deal.kind, number=deal.number, rating=body.rating)
    return _out(deal, review, at)


async def _prompt(db: AsyncSession, deal: Deal) -> ReviewPrompt:
    """The deal's prompt row, added when missing (the deal row is locked by the caller)."""
    if deal.order_id is not None:
        q = select(ReviewPrompt).where(ReviewPrompt.order_id == deal.order_id)
    else:
        q = select(ReviewPrompt).where(ReviewPrompt.sale_id == deal.sale_id)
    row = await db.scalar(q)
    if row is None:
        row = ReviewPrompt(
            user_id=deal.user_id, kind=deal.kind, order_id=deal.order_id, sale_id=deal.sale_id
        )
        db.add(row)
    return row


async def snooze(db: AsyncSession, *, user_id: str, kind: Kind, number: str, at: datetime) -> None:
    """«Не сейчас»: no prompt for this deal for :data:`SNOOZE`. Flushes."""
    deal = await _owned(db, user_id, kind, number, lock=True)
    _allowed(deal, at)
    row = await _prompt(db, deal)
    row.snoozed_until, row.updated_at = at + SNOOZE, at
    await db.flush()


async def dismiss(db: AsyncSession, *, user_id: str, kind: Kind, number: str, at: datetime) -> None:
    """×: no prompt for this deal again (the account page still offers it). Flushes."""
    deal = await _owned(db, user_id, kind, number, lock=True)
    _allowed(deal, at)
    row = await _prompt(db, deal)
    row.dismissed, row.updated_at = True, at
    await db.flush()


async def pending(db: AsyncSession, *, user_id: str, at: datetime) -> ReviewPendingOut:
    """The deal the prompt asks about now, or none."""
    deal = await pending_for(db, user_id, at)
    if deal is None or deal.done_at is None:
        return ReviewPendingOut(deal=None)
    return ReviewPendingOut(
        deal=DealOut(
            kind=deal.kind,
            number=deal.number,
            title=deal.title,
            image_url=deal.image_url,
            rarity_color=deal.rarity_color,
            items=deal.items,
            done_at=deal.done_at,
        )
    )
