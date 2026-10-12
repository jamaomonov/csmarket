"""«Заявки на выплату»: the queue's rows, tabs, search and totals, and the dashboard's
«К выплате» (spec 2026-10-08 §7; admin review 2026-10-12 M1, M10).

«К выплате» is oldest first (``to_pay_at``, the request that waited longest on top); the other
tabs and a search (``all``) are newest first. ``q`` finds a request by sale-number prefix, the
card's last four, the seller's display name (a substring) or Steam ID (exact). The totals count
since midnight in Tashkent.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal

from sqlalchemy import ColumnElement, DateTime, Select, and_, func, literal, or_, select, tuple_
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.clock import now
from csmarket.core.cursor import decode_cursor, encode_cursor
from csmarket.core.money import wire_uzs
from csmarket.modules.sales.admin_claims import claim_until
from csmarket.modules.sales.admin_risk import row_flags
from csmarket.modules.sales.admin_sales import ATTENTION_OPEN_SQL, payout_row, user_of, users_by_id
from csmarket.modules.sales.admin_schemas import (
    PayoutCountsOut,
    PayoutRowOut,
    PayoutsPageOut,
    PayoutTab,
    PayoutTotalsOut,
)
from csmarket.modules.sales.models import PayoutCard, PayoutRequest, Sale
from csmarket.modules.users.api import User

TASHKENT = timezone(timedelta(hours=5))
#: The moment a request became payable (``to_pay_at``; its creation if a row lacks it).
_DUE = func.coalesce(PayoutRequest.to_pay_at, PayoutRequest.created_at)


async def rows(db: AsyncSession, requests: list[PayoutRequest]) -> list[PayoutRowOut]:
    """Queue rows for ``requests``: sales, cards, users and flags in a few queries."""
    if not requests:
        return []
    numbers = dict(
        (
            await db.execute(
                select(Sale.id, Sale.number).where(Sale.id.in_({r.sale_id for r in requests}))
            )
        ).all()
    )
    cards = {
        c.id: c
        for c in await db.scalars(
            select(PayoutCard).where(PayoutCard.id.in_({r.card_id for r in requests}))
        )
    }
    claimers = [r.claimed_by for r in requests if r.claimed_by and claim_until(r)]
    users = await users_by_id(db, [*(r.user_id for r in requests), *claimers])
    flags = await row_flags(db, requests, cards)
    out = []
    for r in requests:
        row = payout_row(
            r, number=numbers[r.sale_id], card=cards[r.card_id], user=user_of(users, r.user_id)
        )
        until = claim_until(r)
        if until is not None and r.claimed_by is not None:
            row.claimed_by, row.claimed_until = user_of(users, r.claimed_by), until
        row.flags = flags.get(r.id, [])
        out.append(row)
    return out


def _search(q: str) -> ColumnElement[bool]:
    """``q`` as a sale-number prefix, a last four, a name substring or a Steam ID."""
    text = q.strip()
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return or_(
        Sale.number.startswith(text.upper(), autoescape=True),
        PayoutCard.last4 == text,
        User.display_name.ilike(f"%{escaped}%", escape="\\"),
        User.steam_id == text,
    )


def _page_stmt(
    tab: PayoutTab, q: str | None, cursor: str | None, limit: int
) -> Select[PayoutRequest]:
    stmt = select(PayoutRequest)
    if tab != "all":
        stmt = stmt.where(PayoutRequest.status == tab)
    if q and q.strip():
        stmt = (
            stmt.join(Sale, Sale.id == PayoutRequest.sale_id)
            .join(PayoutCard, PayoutCard.id == PayoutRequest.card_id)
            .join(User, User.id == PayoutRequest.user_id)
            .where(_search(q))
        )
    if tab == "to_pay":
        stmt = stmt.order_by(_DUE.asc(), PayoutRequest.id.asc())
        if cursor is not None:
            stamp, rid = decode_cursor(cursor)
            # A row comparison: after (stamp, rid) in the ascending order.
            stmt = stmt.where(
                tuple_(_DUE, PayoutRequest.id)
                > tuple_(literal(stamp, DateTime(timezone=True)), literal(rid, UUID(as_uuid=False)))
            )
    else:
        stmt = stmt.order_by(PayoutRequest.created_at.desc(), PayoutRequest.id.desc())
        if cursor is not None:
            stamp, rid = decode_cursor(cursor)
            stmt = stmt.where(
                or_(
                    PayoutRequest.created_at < stamp,
                    and_(PayoutRequest.created_at == stamp, PayoutRequest.id < rid),
                )
            )
    return stmt.limit(limit + 1)


def _cursor_of(tab: PayoutTab, last: PayoutRequest) -> str:
    if tab == "to_pay":
        return encode_cursor(last.to_pay_at or last.created_at, last.id)
    return encode_cursor(last.created_at, last.id)


def tashkent_midnight(at: datetime | None = None) -> datetime:
    """Today's 00:00 in Tashkent, as an aware datetime."""
    day = (at or now()).astimezone(TASHKENT).date()
    return datetime.combine(day, time(0), tzinfo=TASHKENT)


async def payout_totals(db: AsyncSession) -> PayoutTotalsOut:
    """Payable now; paid and rejected since midnight in Tashkent."""
    since = tashkent_midnight()
    to_pay_count, to_pay = (
        await db.execute(
            select(func.count(), func.coalesce(func.sum(PayoutRequest.amount_uzs), 0)).where(
                PayoutRequest.status == "to_pay"
            )
        )
    ).one()
    paid_count, paid = (
        await db.execute(
            select(func.count(), func.coalesce(func.sum(PayoutRequest.amount_uzs), 0)).where(
                PayoutRequest.status == "paid", PayoutRequest.paid_at >= since
            )
        )
    ).one()
    rejected = await db.scalar(
        select(func.count()).where(
            PayoutRequest.status == "rejected", PayoutRequest.rejected_at >= since
        )
    )
    return PayoutTotalsOut(
        to_pay_count=int(to_pay_count),
        to_pay_uzs=wire_uzs(Decimal(to_pay)),
        paid_today_count=int(paid_count),
        paid_today_uzs=wire_uzs(Decimal(paid)),
        rejected_today_count=int(rejected or 0),
    )


async def list_payouts(
    db: AsyncSession,
    *,
    status: PayoutTab,
    cursor: str | None,
    limit: int,
    q: str | None = None,
) -> PayoutsPageOut:
    """One tab (``to_pay`` oldest first, the rest newest first), every tab's count, totals."""
    found = list((await db.scalars(_page_stmt(status, q, cursor, limit))).all())
    page = found[:limit]
    counts = dict(
        (
            await db.execute(
                select(PayoutRequest.status, func.count()).group_by(PayoutRequest.status)
            )
        ).all()
    )
    return PayoutsPageOut(
        items=await rows(db, page),
        counts=PayoutCountsOut(**{k: int(v) for k, v in counts.items()}),
        totals=await payout_totals(db),
        next_cursor=_cursor_of(status, page[-1]) if len(found) > limit else None,
    )


@dataclass(frozen=True)
class PayoutsSummary:
    """The dashboard's «К выплате»."""

    to_pay_count: int
    to_pay_uzs: Decimal
    #: Sales with an open attention (any reason).
    sales_attention: int = 0


async def payouts_summary(db: AsyncSession) -> PayoutsSummary:
    """How many card payouts are payable now, their sum, and the sales waiting for a look."""
    count, total = (
        await db.execute(
            select(func.count(), func.coalesce(func.sum(PayoutRequest.amount_uzs), 0)).where(
                PayoutRequest.status == "to_pay"
            )
        )
    ).one()
    flagged = await db.scalar(select(func.count()).select_from(Sale).where(ATTENTION_OPEN_SQL))
    return PayoutsSummary(
        to_pay_count=int(count), to_pay_uzs=Decimal(total), sales_attention=int(flagged or 0)
    )


__all__ = [
    "PayoutsSummary",
    "list_payouts",
    "payout_totals",
    "payouts_summary",
    "rows",
    "tashkent_midnight",
]
