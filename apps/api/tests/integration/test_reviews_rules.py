"""Rule 7 (spec 2026-10-23-reviews): which deal may be reviewed, and the newest one to ask about."""

from __future__ import annotations

from datetime import timedelta

import pytest
from csmarket.core.clock import now
from csmarket.modules.public_api.keys import issue
from csmarket.modules.reviews.deals import find_deal, pending_for, reviewable
from csmarket.modules.reviews.models import ReviewPrompt
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.payments_factory import make_user
from tests.integration.reviews_factory import (
    card_sale,
    credited_sale,
    delivered_order,
    make_review,
)

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize(
    ("status", "ok"),
    [("delivered", True), ("trade_sent", False), ("returned", False), ("failed", False)],
)
async def test_an_order_is_reviewable_only_delivered(
    db_session: AsyncSession, status: str, ok: bool
) -> None:
    order = await delivered_order(db_session, status=status)
    deal = await find_deal(db_session, "market", order.number)
    assert deal is not None
    assert reviewable(deal, now()) is ok


async def test_a_partner_api_order_is_never_reviewable(db_session: AsyncSession) -> None:
    user = await make_user(db_session)
    user.usd_wallet_enabled = True
    key, _token = await issue(db_session, user=user)
    order = await delivered_order(
        db_session,
        user=user,
        channel="api",
        api_key_id=key.id,
        client_order_id="c-1",
        pricing_profile="retail",
    )
    deal = await find_deal(db_session, "market", order.number)
    assert deal is not None
    assert not reviewable(deal, now())
    assert await pending_for(db_session, user.id, now()) is None


@pytest.mark.parametrize(
    ("status", "ok"), [("credited", True), ("hold", False), ("closed", False), ("reverted", False)]
)
async def test_a_balance_sale_is_reviewable_once_credited(
    db_session: AsyncSession, status: str, ok: bool
) -> None:
    sale = await credited_sale(db_session, status=status)
    deal = await find_deal(db_session, "sale", sale.number)
    assert deal is not None
    assert reviewable(deal, now()) is ok


@pytest.mark.parametrize(
    ("request_status", "ok"),
    [("paid", True), ("to_pay", False), ("waiting_hold", False), ("rejected", False)],
)
async def test_a_card_sale_is_reviewable_once_its_payout_is_paid(
    db_session: AsyncSession, request_status: str, ok: bool
) -> None:
    sale, _ = await card_sale(db_session, request_status=request_status)
    deal = await find_deal(db_session, "sale", sale.number)
    assert deal is not None
    assert reviewable(deal, now()) is ok


async def test_the_fourteen_day_edge(db_session: AsyncSession) -> None:
    at = now()
    edge = await delivered_order(db_session, delivered_at=at - timedelta(days=14))
    past = await delivered_order(db_session, delivered_at=at - timedelta(days=14, seconds=1))
    inside = await find_deal(db_session, "market", edge.number)
    outside = await find_deal(db_session, "market", past.number)
    assert inside is not None
    assert reviewable(inside, at)
    assert outside is not None
    assert not reviewable(outside, at)


async def test_an_unknown_number_is_no_deal(db_session: AsyncSession) -> None:
    assert await find_deal(db_session, "market", "ZZZZZZZZ") is None
    assert await find_deal(db_session, "sale", "SZZZZZZZ") is None


async def test_pending_is_the_newest_reviewable_deal_of_the_user(db_session: AsyncSession) -> None:
    user = await make_user(db_session)
    await delivered_order(db_session, user=user, days_ago=3)
    newest = await credited_sale(db_session, user=user, days_ago=1)
    await delivered_order(db_session, days_ago=0.5)  # someone else's
    await delivered_order(db_session, user=user, days_ago=15)  # too old
    deal = await pending_for(db_session, user.id, now())
    assert deal is not None
    assert (deal.kind, deal.number, deal.items) == ("sale", newest.number, 2)
    # The sale's picture is its most valuable item (sales_factory.ITEMS).
    assert deal.title == "AK-47 | Redline (Field-Tested)"


async def test_pending_picks_a_paid_card_sale_by_its_payout_time(db_session: AsyncSession) -> None:
    user = await make_user(db_session)
    await delivered_order(db_session, user=user, days_ago=2)
    sale, _ = await card_sale(db_session, user=user, days_ago=1)
    deal = await pending_for(db_session, user.id, now())
    assert deal is not None
    assert deal.number == sale.number


async def test_pending_skips_reviewed_snoozed_and_dismissed(db_session: AsyncSession) -> None:
    user = await make_user(db_session)
    oldest = await delivered_order(db_session, user=user, days_ago=4)
    dismissed = await delivered_order(db_session, user=user, days_ago=3)
    snoozed = await delivered_order(db_session, user=user, days_ago=2)
    reviewed = await delivered_order(db_session, user=user, days_ago=1)
    await make_review(db_session, deal=reviewed)
    db_session.add_all(
        [
            ReviewPrompt(user_id=user.id, kind="market", order_id=dismissed.id, dismissed=True),
            ReviewPrompt(
                user_id=user.id,
                kind="market",
                order_id=snoozed.id,
                snoozed_until=now() + timedelta(days=1),
            ),
        ]
    )
    await db_session.commit()
    deal = await pending_for(db_session, user.id, now())
    assert deal is not None
    assert deal.number == oldest.number


async def test_a_snooze_ends(db_session: AsyncSession) -> None:
    user = await make_user(db_session)
    order = await delivered_order(db_session, user=user, days_ago=5)
    db_session.add(
        ReviewPrompt(
            user_id=user.id,
            kind="market",
            order_id=order.id,
            snoozed_until=now() - timedelta(seconds=1),
        )
    )
    await db_session.commit()
    deal = await pending_for(db_session, user.id, now())
    assert deal is not None
    assert deal.number == order.number


async def test_nothing_pending(db_session: AsyncSession) -> None:
    user = await make_user(db_session)
    assert await pending_for(db_session, user.id, now()) is None
