"""The referrals tables hold their own rules (spec 2026-10-27-referrals «Data»)."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from csmarket.core.clock import now
from csmarket.modules.referrals.models import ReferralPartner, ReferralReward
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.orders_factory import make_order
from tests.integration.payments_factory import make_user

pytestmark = pytest.mark.asyncio


async def _partner(db: AsyncSession, **over: object) -> ReferralPartner:
    user = await make_user(db)
    values: dict[str, object] = {
        "user_id": user.id,
        "code": f"p{user.id[-8:]}",
        "percent": Decimal("1.0"),
        "term_months": 6,
    }
    values.update(over)
    partner = ReferralPartner(**values)
    db.add(partner)
    await db.flush()
    return partner


@pytest.mark.parametrize(
    "over",
    [
        {"percent": Decimal("0.0")},
        {"percent": Decimal("20.1")},
        {"term_months": 0},
        {"term_months": 121},
    ],
)
async def test_percent_and_term_bounds(db_session: AsyncSession, over: dict[str, object]) -> None:
    with pytest.raises(IntegrityError):
        await _partner(db_session, **over)


async def test_forever_and_the_edges_are_allowed(db_session: AsyncSession) -> None:
    await _partner(db_session, percent=Decimal("0.1"), term_months=None)
    await _partner(db_session, percent=Decimal("20.0"), term_months=120)


def _reward(partner: ReferralPartner, order_id: str, user_id: str, amount: int) -> ReferralReward:
    at = now()
    return ReferralReward(
        order_id=order_id,
        partner_id=partner.user_id,
        referred_user_id=user_id,
        base_uzs=Decimal(100_000),
        percent=Decimal("1.0"),
        amount_uzs=Decimal(amount),
        status="held",
        delivered_at=at,
        available_at=at + timedelta(days=8),
    )


async def test_one_reward_per_order(db_session: AsyncSession) -> None:
    partner = await _partner(db_session)
    order = await make_order(db_session)
    db_session.add(_reward(partner, order.id, order.user_id, 1000))
    await db_session.flush()
    db_session.add(_reward(partner, order.id, order.user_id, 1000))
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_reward_amount_positive(db_session: AsyncSession) -> None:
    partner = await _partner(db_session)
    order = await make_order(db_session)
    db_session.add(_reward(partner, order.id, order.user_id, 0))
    with pytest.raises(IntegrityError):
        await db_session.flush()
