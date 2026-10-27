"""Rows for the referrals tests: partners, attributions, rewards."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

from csmarket.core.clock import now
from csmarket.modules.orders.models import Order
from csmarket.modules.referrals.models import (
    HOLD,
    ReferralAttribution,
    ReferralPartner,
    ReferralReward,
)
from csmarket.modules.users.models import User
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.payments_factory import make_user


async def make_partner(
    db: AsyncSession, *, user: User | None = None, **over: object
) -> ReferralPartner:
    """A committed partner (a new account's unless ``user``); ``over`` replaces any column."""
    owner = user or await make_user(db)
    values: dict[str, object] = {
        "user_id": owner.id,
        "code": f"p-{owner.id[-12:]}",
        "percent": Decimal("1.0"),
        "term_months": 6,
    }
    values.update(over)
    partner = ReferralPartner(**values)
    db.add(partner)
    await db.commit()
    return partner


async def attribute(
    db: AsyncSession, *, user: User, partner: ReferralPartner, at: datetime | None = None
) -> ReferralAttribution:
    """Tie ``user`` to ``partner`` (committed)."""
    row = ReferralAttribution(
        user_id=user.id, partner_id=partner.user_id, attributed_at=at or now()
    )
    db.add(row)
    await db.commit()
    return row


async def make_reward(
    db: AsyncSession,
    *,
    partner: ReferralPartner,
    order: Order,
    status: str = "held",
    **over: object,
) -> ReferralReward:
    """A committed reward for ``order`` at the partner's percent."""
    delivered = order.delivered_at or now()
    amount = (order.price_uzs * partner.percent / 100).to_integral_value(rounding="ROUND_FLOOR")
    values: dict[str, object] = {
        "order_id": order.id,
        "partner_id": partner.user_id,
        "referred_user_id": order.user_id,
        "base_uzs": order.price_uzs,
        "percent": partner.percent,
        "amount_uzs": amount,
        "status": status,
        "delivered_at": delivered,
        "available_at": delivered + HOLD,
        "credited_at": delivered + HOLD + timedelta(hours=1) if status == "credited" else None,
        "cancelled_reason": "rolled_back" if status == "cancelled" else None,
    }
    values.update(over)
    reward = ReferralReward(**values)
    db.add(reward)
    await db.commit()
    return reward


__all__ = ["Decimal", "attribute", "make_partner", "make_reward"]
