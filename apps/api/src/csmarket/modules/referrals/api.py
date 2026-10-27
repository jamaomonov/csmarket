"""What other modules may import from ``referrals``."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.clock import now
from csmarket.modules.referrals.models import (
    REF_COOKIE,
    ReferralAttribution,
    ReferralPartner,
    ReferralReward,
    ReferralVisitDay,
)


async def credited_between(db: AsyncSession, *, since: datetime, until: datetime) -> Decimal:
    """What partners were credited in ``[since, until)``, soʻm (analytics' «Партнёрам»)."""
    r = ReferralReward
    total = await db.scalar(
        select(func.coalesce(func.sum(r.amount_uzs), 0)).where(
            r.status == "credited", r.credited_at >= since, r.credited_at < until
        )
    )
    return Decimal(total or 0)


async def restart_after_unban(db: AsyncSession, *, user_id: str) -> None:
    """An unbanned partner earns again from now: deliveries of the ban days never do (as a
    partner switched off and back on). Nothing for an account that is not a partner."""
    await db.execute(
        update(ReferralPartner).where(ReferralPartner.user_id == user_id).values(active_since=now())
    )


__all__ = [
    "REF_COOKIE",
    "ReferralAttribution",
    "ReferralPartner",
    "ReferralReward",
    "ReferralVisitDay",
    "credited_between",
    "restart_after_unban",
]
