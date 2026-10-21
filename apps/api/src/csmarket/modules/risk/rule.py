"""The risk verdict: does a kassa payment pass or wait for an admin (spec 2026-10-21).

Asked by ``payments.hooks.settle`` before money is credited or an order is paid. A user's
settles are serialised by a transaction-scoped advisory lock, so two kassas paying at once
cannot both slip under a limit. Fail-closed (owner ruling 5): any error is a hold.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.clock import now
from csmarket.core.logging import get_logger
from csmarket.modules.payments.models import Payment
from csmarket.modules.risk.models import HoldReason, KassaReviewLimit, UserRiskPolicy

log = get_logger("csmarket.risk.rule")


class Verdict(BaseModel):
    """Pass, or hold with the reason, the window sum and the limit it broke."""

    model_config = ConfigDict(frozen=True)

    hold: bool
    reason: HoldReason | None = None
    window_sum_uzs: Decimal | None = None
    limit_uzs: Decimal | None = None


PASS = Verdict(hold=False)


async def lock_user(db: AsyncSession, user_id: str) -> None:
    """Serialise this user's settles until the transaction ends."""
    await db.execute(select(func.pg_advisory_xact_lock(func.hashtext(f"risk:user:{user_id}"))))


async def money_in(
    db: AsyncSession,
    *,
    user_id: str,
    hours: int,
    provider: str | None = None,
    exclude_payment_id: str | None = None,
) -> Decimal:
    """The user's kassa money that stayed with us in the last ``hours`` (held included)."""
    q = select(func.coalesce(func.sum(Payment.amount_uzs), 0)).where(
        Payment.user_id == user_id,
        Payment.status == "succeeded",
        Payment.succeeded_at >= now() - timedelta(hours=hours),
    )
    if provider is not None:
        q = q.where(Payment.provider == provider)
    if exclude_payment_id is not None:
        q = q.where(Payment.id != exclude_payment_id)
    return Decimal((await db.scalar(q)) or 0)


async def _kassa_limit(db: AsyncSession, payment: Payment) -> Verdict:
    row = await db.get(KassaReviewLimit, payment.provider)
    if row is None or not row.enabled:
        return PASS
    total = payment.amount_uzs + await money_in(
        db,
        user_id=payment.user_id,
        hours=row.window_hours,
        provider=payment.provider,
        exclude_payment_id=payment.id,
    )
    if total <= row.max_amount_uzs:
        return PASS
    return Verdict(
        hold=True, reason="kassa_limit", window_sum_uzs=total, limit_uzs=row.max_amount_uzs
    )


async def _user_limit(db: AsyncSession, payment: Payment, policy: UserRiskPolicy) -> Verdict:
    if policy.max_amount_uzs is None:
        return PASS
    total = payment.amount_uzs + await money_in(
        db, user_id=payment.user_id, hours=policy.window_hours, exclude_payment_id=payment.id
    )
    if total <= policy.max_amount_uzs:
        return PASS
    return Verdict(
        hold=True, reason="user_limit", window_sum_uzs=total, limit_uzs=policy.max_amount_uzs
    )


async def _judge(db: AsyncSession, payment: Payment) -> Verdict:
    policy = await db.get(UserRiskPolicy, payment.user_id)
    if policy is not None and policy.trusted:
        return PASS
    kassa = await _kassa_limit(db, payment)
    if kassa.hold or policy is None:
        return kassa
    return await _user_limit(db, payment, policy)


async def verdict(db: AsyncSession, payment: Payment) -> Verdict:
    """Pass or hold ``payment`` (not yet ``succeeded``); never raises.

    Takes the user's advisory lock first; the reads run in a savepoint so a failed query
    leaves the caller's transaction usable, and any error is a ``check_failed`` hold.

    Args:
        db: The caller's session, inside the settle transaction.
        payment: The attempt being settled.

    Returns:
        The verdict; a hold carries the reason and, for a limit, the sum and the limit.
    """
    try:
        await lock_user(db, payment.user_id)
        async with db.begin_nested():
            return await _judge(db, payment)
    except Exception as exc:  # noqa: BLE001 -- fail-closed by owner ruling 5
        log.warning(
            "payments.risk.check_failed",
            number=payment.number,
            provider=payment.provider,
            error=type(exc).__name__,
        )
        return Verdict(hold=True, reason="check_failed")
