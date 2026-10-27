"""The partner's own view: its terms, its numbers this Tashkent month and all time, its money,
and its rewards — amounts and dates only, never the buyer or the order (spec
2026-10-27-referrals «Partner page»)."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.clock import now
from csmarket.core.errors import NotFoundError
from csmarket.modules.referrals import cursor
from csmarket.modules.referrals.models import (
    ReferralAttribution,
    ReferralPartner,
    ReferralReward,
    ReferralVisitDay,
)
from csmarket.modules.referrals.schemas import (
    Counts,
    PartnerMeOut,
    PartnerRewardOut,
    PartnerRewardsOut,
)
from csmarket.modules.referrals.stats import som

TASHKENT = ZoneInfo("Asia/Tashkent")
PAGE = 20


def month_start(at: datetime) -> datetime:
    """The first instant of ``at``'s Tashkent month."""
    local = at.astimezone(TASHKENT)
    return local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


async def own_partner(db: AsyncSession, user_id: str) -> ReferralPartner:
    """The signed-in account's partner row.

    Raises:
        NotFoundError: ``code="not_a_partner"``.
    """
    partner = await db.get(ReferralPartner, user_id)
    if partner is None:
        raise NotFoundError("not a partner", code="not_a_partner")
    return partner


async def counts(db: AsyncSession, partner_id: str, since: datetime | None) -> Counts:
    """Visits, accounts, purchases and earnings of ``partner_id`` since ``since`` (or ever)."""
    v, a, r = ReferralVisitDay, ReferralAttribution, ReferralReward
    visits = select(func.coalesce(func.sum(v.visits), 0)).where(v.partner_id == partner_id)
    accounts = select(func.count()).select_from(a).where(a.partner_id == partner_id)
    money = select(func.count(), func.coalesce(func.sum(r.amount_uzs), 0)).where(
        r.partner_id == partner_id, r.status != "cancelled"
    )
    if since is not None:
        visits = visits.where(v.day >= since.date())
        accounts = accounts.where(a.attributed_at >= since)
        money = money.where(r.delivered_at >= since)
    purchases, earned = (await db.execute(money)).one()
    return Counts(
        visits=int(await db.scalar(visits) or 0),
        accounts=int(await db.scalar(accounts) or 0),
        purchases=int(purchases),
        earned_uzs=som(earned),
    )


async def overview(db: AsyncSession, user_id: str) -> PartnerMeOut:
    """The partner page's head."""
    partner = await own_partner(db, user_id)
    r = ReferralReward
    held, next_at, credited = (
        await db.execute(
            select(
                func.sum(r.amount_uzs).filter(r.status == "held"),
                func.min(r.available_at).filter(r.status == "held"),
                func.sum(r.amount_uzs).filter(r.status == "credited"),
            ).where(r.partner_id == partner.user_id)
        )
    ).one()
    return PartnerMeOut(
        code=partner.code,
        percent=partner.percent,
        term_months=partner.term_months,
        active=partner.active,
        month=await counts(db, partner.user_id, month_start(now())),
        all_time=await counts(db, partner.user_id, None),
        held_uzs=som(held),
        next_available_at=next_at,
        credited_uzs=som(credited),
    )


async def rewards(db: AsyncSession, user_id: str, *, after: str | None) -> PartnerRewardsOut:
    """:data:`PAGE` of the partner's rewards, newest delivery first."""
    partner = await own_partner(db, user_id)
    r = ReferralReward
    q = (
        select(r)
        .where(r.partner_id == partner.user_id)
        .order_by(r.delivered_at.desc(), r.order_id.desc())
        .limit(PAGE + 1)
    )
    if (past := cursor.after(after)) is not None:
        q = q.where(past)
    rows = list((await db.scalars(q)).all())
    page = rows[:PAGE]
    last = page[-1] if len(rows) > PAGE else None
    return PartnerRewardsOut(
        items=[
            PartnerRewardOut(
                delivered_at=w.delivered_at,
                base_uzs=som(w.base_uzs),
                amount_uzs=som(w.amount_uzs),
                status=w.status,  # type: ignore[arg-type]  # DB check constraint guarantees the set
                available_at=w.available_at,
            )
            for w in page
        ],
        next_cursor=cursor.encode(last.delivered_at, last.order_id) if last else None,
    )


__all__ = ["PAGE", "counts", "month_start", "overview", "own_partner", "rewards"]
