"""The desk's figures and the owner's withdrawals (spec 2026-10-29-desk «Profit», «The
owner's share of our Skinslink balance»).

Profit and Skinslink revenue are sums of ``desk_entries`` rows dated inside the window
(Tashkent days, inclusive). The share is all-time: Skinslink money the desk booked less what
the owner marked as taken out — a figure only (owner ruling 2026-10-29).
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.clock import now
from csmarket.core.ids import new_id
from csmarket.modules.desk.models import DeskDeal, DeskEntry, DeskItem, DeskWithdrawal
from csmarket.modules.desk.money import plain
from csmarket.modules.desk.schemas import (
    SummaryOut,
    WithdrawalIn,
    WithdrawalOut,
    WithdrawalsOut,
)

TASHKENT = ZoneInfo("Asia/Tashkent")
DEFAULT_DAYS = 30


def window(start: date | None, end: date | None) -> tuple[datetime, datetime]:
    """``[start 00:00, end + 1 day 00:00)`` in Tashkent; default the last 30 days."""
    today = now().astimezone(TASHKENT).date()
    last = end or today
    first = start or last - timedelta(days=DEFAULT_DAYS - 1)
    return (
        datetime.combine(first, time(), tzinfo=TASHKENT),
        datetime.combine(last + timedelta(days=1), time(), tzinfo=TASHKENT),
    )


async def _sum(db: AsyncSession, column: object, *where: object) -> Decimal:
    total = await db.scalar(select(func.coalesce(func.sum(column), 0)).where(*where))  # type: ignore[arg-type]  # a numeric column
    return Decimal(total or 0)


async def summary(db: AsyncSession, start: date | None, end: date | None) -> SummaryOut:
    """The five figures and the counts for the window."""
    lo, hi = window(start, end)
    in_window = (DeskEntry.at >= lo, DeskEntry.at < hi)
    resolved = await db.scalar(
        select(func.count(func.distinct(DeskEntry.item_id))).where(
            *in_window, DeskEntry.kind != "revert"
        )
    )
    closed = await db.scalar(
        select(func.count()).where(
            DeskDeal.status == "closed", DeskDeal.updated_at >= lo, DeskDeal.updated_at < hi
        )
    )
    unresolved = DeskItem.state.in_(("open", "sent"))
    in_transit = await _sum(
        db,
        DeskItem.cost_usd,
        DeskItem.destination == "skinslink",
        unresolved,
        DeskItem.deal_id.in_(select(DeskDeal.id).where(DeskDeal.status.in_(("paid", "received")))),
    )
    booked = await _sum(db, DeskEntry.revenue_usd)
    taken = await _sum(db, DeskWithdrawal.amount_usd)
    return SummaryOut(
        profit_usd=plain(await _sum(db, DeskEntry.profit_usd, *in_window)) or "0",
        revenue_usd=plain(await _sum(db, DeskEntry.revenue_usd, *in_window)) or "0",
        deals_closed=int(closed or 0),
        items_resolved=int(resolved or 0),
        in_transit_usd=plain(in_transit) or "0",
        stock_usd=plain(
            await _sum(
                db, DeskItem.cost_usd, DeskItem.destination == "stock", DeskItem.state == "open"
            )
        )
        or "0",
        skinslink_share_usd=plain(booked - taken) or "0",
    )


def _withdrawal_out(w: DeskWithdrawal) -> WithdrawalOut:
    return WithdrawalOut(id=w.id, amount_usd=plain(w.amount_usd) or "0", note=w.note, at=w.at)


async def add_withdrawal(db: AsyncSession, body: WithdrawalIn) -> WithdrawalOut:
    """«Вывел себе»: the share drops by ``amount_usd``."""
    row = DeskWithdrawal(id=new_id(), amount_usd=body.amount_usd, note=body.note, at=now())
    db.add(row)
    await db.flush()
    return _withdrawal_out(row)


async def list_withdrawals(db: AsyncSession) -> WithdrawalsOut:
    """Newest first, the last 100."""
    rows = await db.scalars(select(DeskWithdrawal).order_by(DeskWithdrawal.at.desc()).limit(100))
    return WithdrawalsOut(items=[_withdrawal_out(w) for w in rows])


__all__ = ["TASHKENT", "add_withdrawal", "list_withdrawals", "summary", "window"]
