"""Rewards: written for delivered orders of attributed buyers, credited after the hold.

:func:`accrue` pulls (ADR-0026): every hour it finds orders delivered in the last
:data:`LOOKBACK` whose buyer a partner brought, inside the partner's term, and writes one
``held`` reward per order. ``orders`` knows nothing of ``referrals``.

:func:`settle` takes the rewards whose hold is over:

- a ``rolled_back`` attention on the order's trade or purchase, now or ever (``rolled_back_at``,
  resolved or written over) → ``cancelled``;
- another unresolved attention, a banned partner or a frozen wallet → stays ``held``;
- else the wallet is credited (``referral_reward:{order_id}``) and the reward ``credited``.

A waiting reward gets ``checked_at``; each run takes the never-checked first, then the longest
unchecked, so waiting rows never starve the others.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, literal_column, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.clock import now
from csmarket.core.errors import ConflictError
from csmarket.core.logging import get_logger
from csmarket.modules.lisskins.api import LisskinsPurchase
from csmarket.modules.orders.api import Order, SkinTrade
from csmarket.modules.referrals.models import (
    HOLD,
    ReferralAttribution,
    ReferralPartner,
    ReferralReward,
)
from csmarket.modules.skinslink.api import SkinslinkPurchase
from csmarket.modules.users.api import User
from csmarket.modules.wallet.api import credit_referral_reward

log = get_logger("csmarket.referrals.rewards")

#: How far back :func:`accrue` looks for deliveries; a job down longer than this misses some.
LOOKBACK = timedelta(days=14)
#: A reward still held this long past its hold is stuck (alert: ReferralRewardsStuck).
STUCK_AFTER = timedelta(days=3)
HoldState = Literal["rolled_back", "open", "clear"]


class SettleResult(BaseModel):
    """What one :func:`settle` run did."""

    model_config = ConfigDict(frozen=True)

    credited: int = 0
    cancelled: int = 0
    waiting: int = 0


async def accrue(db: AsyncSession) -> int:
    """Write a ``held`` reward for each newly delivered order a partner earns on; commits.

    Returns:
        How many rewards were written.
    """
    o, a, p = Order, ReferralAttribution, ReferralPartner
    amount = func.floor(o.price_uzs * p.percent / 100)
    term_end = a.attributed_at + func.make_interval(0, p.term_months)
    rows = (
        select(
            o.id,
            p.user_id,
            o.user_id,
            o.price_uzs,
            p.percent,
            amount,
            literal_column("'held'"),
            o.delivered_at,
            o.delivered_at + HOLD,
        )
        .join(a, a.user_id == o.user_id)
        .join(p, p.user_id == a.partner_id)
        .join(User, User.id == p.user_id)
        .where(
            o.status == "delivered",
            o.api_key_id.is_(None),
            o.delivered_at >= now() - LOOKBACK,
            o.delivered_at >= a.attributed_at,
            o.delivered_at >= p.active_since,
            p.term_months.is_(None) | (o.delivered_at < term_end),
            p.active.is_(True),
            User.banned_at.is_(None),
            amount > 0,
        )
    )
    r = ReferralReward
    stmt = (
        insert(r)
        .from_select(
            [
                r.order_id,
                r.partner_id,
                r.referred_user_id,
                r.base_uzs,
                r.percent,
                r.amount_uzs,
                r.status,
                r.delivered_at,
                r.available_at,
            ],
            rows,
        )
        .on_conflict_do_nothing(index_elements=[r.order_id])
        .returning(r.order_id)
    )
    written = len((await db.execute(stmt)).all())
    await db.commit()
    if written:
        log.info("referrals.rewards.accrued", count=written)
    return written


async def hold_state(db: AsyncSession, order_ids: list[str]) -> dict[str, HoldState]:
    """Each order's attention, from its Waxpeer trade or its Skinslink / LIS-SKINS purchase."""
    states: dict[str, HoldState] = dict.fromkeys(order_ids, "clear")
    for table in (SkinTrade, SkinslinkPurchase, LisskinsPurchase):
        found = await db.execute(
            select(
                table.order_id, table.attention_reason, table.resolved_at, table.rolled_back_at
            ).where(
                table.order_id.in_(order_ids),
                table.attention_reason.is_not(None) | table.rolled_back_at.is_not(None),
            )
        )
        for order_id, reason, resolved_at, rolled_back_at in found.all():
            if reason == "rolled_back" or rolled_back_at is not None:
                states[order_id] = "rolled_back"
            elif resolved_at is None and states[order_id] == "clear":
                states[order_id] = "open"
    return states


def _cancel(reward: ReferralReward, partner_code: str) -> None:
    reward.status = "cancelled"
    reward.cancelled_reason = "rolled_back"
    log.info("referrals.reward.cancelled", partner=partner_code, amount=str(reward.amount_uzs))


async def _credit(db: AsyncSession, reward: ReferralReward, partner_code: str) -> bool:
    try:
        async with db.begin_nested():
            await credit_referral_reward(
                db, user_id=reward.partner_id, order_id=reward.order_id, amount=reward.amount_uzs
            )
    except ConflictError:  # the partner's wallet is frozen: wait
        return False
    await db.execute(
        update(ReferralReward)
        .where(ReferralReward.order_id == reward.order_id)
        .values(status="credited", credited_at=now())
    )
    log.info("referrals.reward.credited", partner=partner_code, amount=str(reward.amount_uzs))
    return True


async def settle(db: AsyncSession, *, limit: int = 200) -> SettleResult:
    """Cancel, credit or keep waiting each reward whose hold is over; commits once."""
    r = ReferralReward
    due = (
        await db.execute(
            select(r, ReferralPartner.code, User.banned_at)
            .join(ReferralPartner, ReferralPartner.user_id == r.partner_id)
            .join(User, User.id == r.partner_id)
            .where(r.status == "held", r.available_at <= now())
            .order_by(r.checked_at.asc().nulls_first(), r.available_at)
            .limit(limit)
            .with_for_update(of=r, skip_locked=True)
        )
    ).all()
    states = await hold_state(db, [row[0].order_id for row in due])
    credited = cancelled = waiting = 0
    for reward, code, banned_at in due:
        state = states[reward.order_id]
        if state == "rolled_back":
            _cancel(reward, code)
            cancelled += 1
        elif state != "open" and banned_at is None and await _credit(db, reward, code):
            credited += 1
        else:
            reward.checked_at = now()
            waiting += 1
    await db.commit()
    return SettleResult(credited=credited, cancelled=cancelled, waiting=waiting)


async def stuck_count(db: AsyncSession) -> int:
    """Rewards still ``held`` :data:`STUCK_AFTER` past their hold (an attention nobody resolves,
    a frozen wallet, a banned partner, or the job not running)."""
    r = ReferralReward
    q = select(func.count()).where(r.status == "held", r.available_at < now() - STUCK_AFTER)
    return int(await db.scalar(q) or 0)


__all__ = [
    "LOOKBACK",
    "STUCK_AFTER",
    "HoldState",
    "SettleResult",
    "accrue",
    "hold_state",
    "settle",
    "stuck_count",
]
