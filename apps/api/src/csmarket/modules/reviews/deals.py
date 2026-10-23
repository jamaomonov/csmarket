"""Which deal a user may review now (spec rule 7), and the newest one to ask about.

A deal is an order (``market``) or a sale (``sale``). It succeeded at:

- an order: status ``delivered``, placed on the site (a partner-API order is a bot's, never
  reviewed), at ``delivered_at``;
- a sale to the balance: status ``credited``, at ``credited_at``;
- a sale to a card: its payout request ``paid``, at the request's ``paid_at``.

It may be reviewed, and its review edited, until :data:`REVIEW_WINDOW` after that moment.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict
from sqlalchemy import and_, case, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from csmarket.modules.orders.api import Order
from csmarket.modules.reviews.models import REVIEW_WINDOW, Review, ReviewPrompt
from csmarket.modules.sales.api import PayoutRequest, Sale, SaleItem
from csmarket.modules.skins.api import SkinItem

Kind = Literal["market", "sale"]

#: When a sale succeeded: the balance credit, or the card payout marked paid.
_SALE_DONE = case((Sale.payout_to == "balance", Sale.credited_at), else_=PayoutRequest.paid_at)
_SALE_OK = or_(
    and_(Sale.payout_to == "balance", Sale.status == "credited"),
    and_(Sale.payout_to == "card", PayoutRequest.status == "paid"),
)
_ORDER_OK = and_(Order.status == "delivered", Order.channel == "site")


class Deal(BaseModel):
    """One order or sale as the review rules see it."""

    model_config = ConfigDict(frozen=True)

    kind: Kind
    number: str
    user_id: str
    order_id: str | None
    sale_id: str | None
    #: When it succeeded (rule 7); ``None`` while it has not.
    done_at: datetime | None
    #: The skin's name; a sale's most valuable item.
    title: str
    image_url: str | None
    items: int


def reviewable(deal: Deal, at: datetime) -> bool:
    """Succeeded, at most :data:`REVIEW_WINDOW` ago (the edge itself still counts)."""
    return deal.done_at is not None and at - deal.done_at <= REVIEW_WINDOW


def editable_until(deal: Deal) -> datetime | None:
    """The last moment the deal may be reviewed; ``None`` while it has not succeeded."""
    return deal.done_at + REVIEW_WINDOW if deal.done_at is not None else None


async def find_deal(
    db: AsyncSession, kind: Kind, number: str, *, lock: bool = False
) -> Deal | None:
    """The deal ``number`` of ``kind``, whoever owns it; ``None`` when there is none.

    ``lock`` takes the order's or the sale's row lock, so two first reviews of one deal queue
    up instead of racing the unique constraint.
    """
    if kind == "market":
        return await _find_order(db, number, lock=lock)
    return await _find_sale(db, number, lock=lock)


async def _find_order(db: AsyncSession, number: str, *, lock: bool) -> Deal | None:
    q = select(Order).where(Order.number == number)
    order = await db.scalar(q.with_for_update() if lock else q)
    if order is None:
        return None
    image = await db.scalar(select(SkinItem.image_url).where(SkinItem.id == order.skin_item_id))
    ok = order.status == "delivered" and order.channel == "site"
    return Deal(
        kind="market",
        number=order.number,
        user_id=order.user_id,
        order_id=order.id,
        sale_id=None,
        done_at=order.delivered_at if ok else None,
        title=order.market_hash_name,
        image_url=image,
        items=1,
    )


async def _find_sale(db: AsyncSession, number: str, *, lock: bool) -> Deal | None:
    q = select(Sale).where(Sale.number == number)
    sale = await db.scalar(q.with_for_update() if lock else q)
    if sale is None:
        return None
    if sale.payout_to == "balance":
        done = sale.credited_at if sale.status == "credited" else None
    else:
        request = await db.scalar(select(PayoutRequest).where(PayoutRequest.sale_id == sale.id))
        done = request.paid_at if request is not None and request.status == "paid" else None
    first = (
        await db.execute(
            select(SaleItem.name, SaleItem.image_url)
            .where(SaleItem.sale_id == sale.id)
            .order_by(SaleItem.price_uzs.desc(), SaleItem.asset_id)
            .limit(1)
        )
    ).first()
    count = await db.scalar(select(func.count()).where(SaleItem.sale_id == sale.id))
    return Deal(
        kind="sale",
        number=sale.number,
        user_id=sale.user_id,
        order_id=None,
        sale_id=sale.id,
        done_at=done,
        title=first.name if first is not None else "",
        image_url=first.image_url if first is not None else None,
        items=int(count or 0),
    )


def _muted(at: datetime) -> ColumnElement[bool]:
    """The user said × for good, or «Не сейчас» and the 3 days are not over."""
    return or_(ReviewPrompt.dismissed.is_(True), ReviewPrompt.snoozed_until > at)


async def pending_for(db: AsyncSession, user_id: str, at: datetime) -> Deal | None:
    """The newest deal of ``user_id`` to ask about now: reviewable, within the window, with no
    review, not dismissed and not snoozed. ``None`` when there is none."""
    since = at - REVIEW_WINDOW
    order_q = (
        select(Order.number, Order.delivered_at.label("done"))
        .where(
            Order.user_id == user_id,
            _ORDER_OK,
            Order.delivered_at >= since,
            ~exists().where(Review.order_id == Order.id),
            ~exists().where(ReviewPrompt.order_id == Order.id, _muted(at)),
        )
        .order_by(Order.delivered_at.desc())
        .limit(1)
    )
    sale_q = (
        select(Sale.number, _SALE_DONE.label("done"))
        .outerjoin(PayoutRequest, PayoutRequest.sale_id == Sale.id)
        .where(
            Sale.user_id == user_id,
            _SALE_OK,
            since <= _SALE_DONE,
            ~exists().where(Review.sale_id == Sale.id),
            ~exists().where(ReviewPrompt.sale_id == Sale.id, _muted(at)),
        )
        .order_by(_SALE_DONE.desc())
        .limit(1)
    )
    market: Kind = "market"
    sale: Kind = "sale"
    found: list[tuple[datetime, Kind, str]] = []
    found.extend((r.done, market, r.number) for r in (await db.execute(order_q)).all())
    found.extend((r.done, sale, r.number) for r in (await db.execute(sale_q)).all())
    if not found:
        return None
    _, kind, number = max(found)
    return await find_deal(db, kind, number)


__all__ = ["Deal", "Kind", "editable_until", "find_deal", "pending_for", "reviewable"]
