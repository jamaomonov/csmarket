"""The reviews tables hold their invariants in the database, whatever the code does."""

from __future__ import annotations

import pytest
from csmarket.modules.reviews.models import Review
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.reviews_factory import credited_sale, delivered_order, make_review

pytestmark = pytest.mark.asyncio


async def test_one_review_per_order(db_session: AsyncSession) -> None:
    order = await delivered_order(db_session)
    await make_review(db_session, deal=order)
    with pytest.raises(IntegrityError):
        await make_review(db_session, deal=order, rating=1)
    await db_session.rollback()


async def test_a_review_names_exactly_one_deal_of_its_kind(db_session: AsyncSession) -> None:
    order = await delivered_order(db_session)
    sale = await credited_sale(db_session)
    # Plain ids: a rollback expires the ORM objects, and an async session cannot lazy-load them.
    order_id, sale_id, user_id = order.id, sale.id, order.user_id
    bad_rows: list[dict[str, str | None]] = [
        {"kind": "market", "order_id": order_id, "sale_id": sale_id},
        {"kind": "market", "order_id": None, "sale_id": None},
        {"kind": "sale", "order_id": order_id, "sale_id": None},
    ]
    for over in bad_rows:
        db_session.add(Review(user_id=user_id, rating=5, locale="ru", **over))
        with pytest.raises(IntegrityError):
            await db_session.flush()
        await db_session.rollback()


@pytest.mark.parametrize(
    "over", [{"rating": 0}, {"rating": 6}, {"locale": "de"}, {"text": ""}, {"text": "x" * 1001}]
)
async def test_rating_locale_and_text_are_checked(
    db_session: AsyncSession, over: dict[str, object]
) -> None:
    order = await delivered_order(db_session)
    with pytest.raises(IntegrityError):
        await make_review(db_session, deal=order, **over)
    await db_session.rollback()
