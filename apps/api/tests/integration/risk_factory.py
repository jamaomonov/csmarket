"""Builders for the risk tests: limits, policies and past kassa payments."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Any

from csmarket.core.clock import now
from csmarket.modules.payments.api import Payment
from csmarket.modules.risk.models import KassaReviewLimit, UserRiskPolicy
from csmarket.modules.users.api import User
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.payments_factory import make_topup


async def set_kassa_limit(
    db: AsyncSession, provider: str, amount: int, *, hours: int = 24, enabled: bool = True
) -> None:
    """Replace ``provider``'s limit row and commit."""
    await db.execute(delete(KassaReviewLimit).where(KassaReviewLimit.provider == provider))
    db.add(
        KassaReviewLimit(
            provider=provider,
            enabled=enabled,
            max_amount_uzs=Decimal(amount),
            window_hours=hours,
        )
    )
    await db.commit()


async def clear_kassa_limits(db: AsyncSession) -> None:
    """Drop every seeded limit so a test starts unlimited."""
    await db.execute(delete(KassaReviewLimit))
    await db.commit()


async def set_policy(db: AsyncSession, user_id: str, **fields: Any) -> None:
    """Replace the user's policy row and commit."""
    await db.execute(delete(UserRiskPolicy).where(UserRiskPolicy.user_id == user_id))
    db.add(UserRiskPolicy(user_id=user_id, **fields))
    await db.commit()


async def succeeded_payment(
    db: AsyncSession,
    user: User,
    *,
    provider: str = "payme",
    amount: int = 500_000,
    hours_ago: float = 0.0,
    status: str = "succeeded",
) -> Payment:
    """A past kassa payment of ``user`` that settled ``hours_ago`` (a top-up's attempt)."""
    topup = await make_topup(db, user=user, amount=Decimal(amount), status="succeeded")
    at = now() - timedelta(hours=hours_ago)
    payment = Payment(
        number=topup.number,
        purpose="topup",
        topup_id=topup.id,
        user_id=user.id,
        provider=provider,
        amount_uzs=Decimal(amount),
        fee_pct=Decimal(0),
        fee_uzs=Decimal(0),
        status=status,
        succeeded_at=at,
        created_at=at,
        updated_at=at,
    )
    db.add(payment)
    await db.commit()
    return payment
