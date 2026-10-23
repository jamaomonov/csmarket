"""Rows for the reviews tests: succeeded deals, reviews, the public switch."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from csmarket.core.clock import now
from csmarket.modules.orders.models import Order
from csmarket.modules.reviews.models import Review, ReviewSettingsRow
from csmarket.modules.sales.models import PayoutRequest, Sale
from csmarket.modules.users.models import User
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.orders_factory import make_order
from tests.integration.sales_factory import make_request, make_sale


async def delivered_order(
    db: AsyncSession, *, user: User | None = None, days_ago: float = 1.0, **over: object
) -> Order:
    """A committed site order delivered ``days_ago`` days ago (``over`` replaces any column)."""
    at = now() - timedelta(days=days_ago)
    values: dict[str, object] = {
        "status": "delivered",
        "paid_with": "wallet",
        "paid_at": at - timedelta(minutes=10),
        "delivered_at": at,
    }
    values.update(over)
    return await make_order(db, user=user, **values)


async def credited_sale(
    db: AsyncSession, *, user: User | None = None, days_ago: float = 1.0, **over: object
) -> Sale:
    """A committed sale to the balance, credited ``days_ago`` days ago."""
    # Any: ``make_sale``'s keywords are typed one by one; these are columns of mixed types
    values: dict[str, Any] = {
        "status": "credited",
        "credited_at": now() - timedelta(days=days_ago),
        "trade_id": 7,
    }
    values.update(over)
    return await make_sale(db, user=user, **values)


async def card_sale(
    db: AsyncSession,
    *,
    user: User | None = None,
    days_ago: float = 1.0,
    request_status: str = "paid",
) -> tuple[Sale, PayoutRequest]:
    """A committed card sale and its payout request; ``paid`` ``days_ago`` days ago."""
    at = now() - timedelta(days=days_ago)
    sale = await make_sale(db, user=user, status="payout", payout_to="card", trade_id=8)
    request = await make_request(
        db,
        sale,
        status=request_status,
        to_pay_at=at - timedelta(hours=1),
        paid_at=at if request_status == "paid" else None,
    )
    return sale, request


async def make_review(
    db: AsyncSession,
    *,
    deal: Order | Sale,
    rating: int = 5,
    text: str | None = None,
    locale: str = "ru",
    **over: object,
) -> Review:
    """A committed review of ``deal`` by its owner (``over`` replaces any column)."""
    market = isinstance(deal, Order)
    values: dict[str, object] = {
        "kind": "market" if market else "sale",
        "order_id": deal.id if market else None,
        "sale_id": None if market else deal.id,
        "user_id": deal.user_id,
        "rating": rating,
        "text": text,
        "locale": locale,
    }
    values.update(over)
    review = Review(**values)
    db.add(review)
    await db.commit()
    return review


async def set_public(db: AsyncSession, on: bool = True) -> None:
    """Switch the public page (row 1); commit."""
    row = await db.get(ReviewSettingsRow, 1)
    if row is None:
        db.add(ReviewSettingsRow(id=1, reviews_public=on))
    else:
        row.reviews_public = on
    await db.commit()
