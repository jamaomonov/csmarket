"""A partner's numbers, read in a few grouped queries (no N+1 over partners).

Visits come from ``referral_visit_days``, accounts from ``referral_attributions``, purchases,
revenue and money from ``referral_rewards`` (a cancelled reward is not a purchase). Months are
Tashkent months.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, SQLColumnExpression, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from csmarket.modules.referrals.models import (
    ReferralAttribution,
    ReferralReward,
    ReferralVisitDay,
)
from csmarket.modules.referrals.schemas import MonthOut, PartnerTotals

TZ = "Asia/Tashkent"
MONTHS = 24


def som(value: Decimal | int | None) -> str:
    """Whole soʻm as a string; ``None`` → ``"0"``."""
    return str(int(value or 0))


def _earning() -> ColumnElement[bool]:
    return ReferralReward.status != "cancelled"


def _only(column: SQLColumnExpression[str], ids: list[str] | None) -> list[ColumnElement[bool]]:
    return [] if ids is None else [column.in_(ids)]


async def partner_totals(db: AsyncSession, ids: list[str] | None) -> dict[str, PartnerTotals]:
    """Each partner's totals (``ids`` ``None`` = every partner); a partner with none is absent."""
    v = ReferralVisitDay
    a = ReferralAttribution
    r = ReferralReward
    visits = await db.execute(
        select(v.partner_id, func.sum(v.visits))
        .where(*_only(v.partner_id, ids))
        .group_by(v.partner_id)
    )
    accounts = await db.execute(
        select(a.partner_id, func.count()).where(*_only(a.partner_id, ids)).group_by(a.partner_id)
    )
    money = await db.execute(
        select(
            r.partner_id,
            func.count().filter(_earning()),
            func.sum(r.base_uzs).filter(_earning()),
            func.sum(r.amount_uzs).filter(r.status == "held"),
            func.sum(r.amount_uzs).filter(r.status == "credited"),
        )
        .where(*_only(r.partner_id, ids))
        .group_by(r.partner_id)
    )
    out: dict[str, dict[str, object]] = {}
    for pid, n in visits.all():
        out.setdefault(pid, {})["visits"] = int(n or 0)
    for pid, n in accounts.all():
        out.setdefault(pid, {})["accounts"] = int(n)
    for pid, n, revenue, held, credited in money.all():
        out.setdefault(pid, {}).update(
            purchases=int(n),
            revenue_uzs=som(revenue),
            held_uzs=som(held),
            credited_uzs=som(credited),
        )
    return {pid: PartnerTotals.model_validate(vals) for pid, vals in out.items()}


def _month(column: SQLColumnExpression[datetime]) -> ColumnElement[date]:
    return cast(func.date_trunc("month", func.timezone(TZ, column)), Date)


async def by_month(db: AsyncSession, partner_id: str) -> list[MonthOut]:
    """The partner's last :data:`MONTHS` Tashkent months with anything in them, newest first."""
    v = ReferralVisitDay
    a = ReferralAttribution
    r = ReferralReward
    rows: dict[date, dict[str, object]] = {}
    vm = cast(func.date_trunc("month", v.day), Date)
    for month, n in await db.execute(
        select(vm, func.sum(v.visits)).where(v.partner_id == partner_id).group_by(vm)
    ):
        rows.setdefault(month, {})["visits"] = int(n or 0)
    am = _month(a.attributed_at)
    for month, n in await db.execute(
        select(am, func.count()).where(a.partner_id == partner_id).group_by(am)
    ):
        rows.setdefault(month, {})["accounts"] = int(n)
    rm = _month(r.delivered_at)
    for month, n, revenue, earned in await db.execute(
        select(
            rm,
            func.count(),
            func.sum(r.base_uzs),
            func.sum(r.amount_uzs),
        )
        .where(r.partner_id == partner_id, _earning())
        .group_by(rm)
    ):
        rows.setdefault(month, {}).update(
            purchases=int(n), revenue_uzs=som(revenue), earned_uzs=som(earned)
        )
    empty = {"visits": 0, "accounts": 0, "purchases": 0, "revenue_uzs": "0", "earned_uzs": "0"}
    newest = sorted(rows.items(), reverse=True)[:MONTHS]
    return [MonthOut.model_validate({**empty, **vals, "month": month}) for month, vals in newest]


__all__ = ["MONTHS", "by_month", "partner_totals", "som"]
