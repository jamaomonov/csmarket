"""The skin-sales P&L of a window and the Skinslink reconciliation (spec 2026-10-13-sales-pnl).

A sale counts from the moment Skinslink completed it: ``credited_at`` for a payout to the
balance, the request's ``to_pay_at`` for a card (a card sale has no ``credited_at``). Each row
carries the CBU rate of the sale's creation, read from ``fx_snapshots`` by a correlated
subquery. Reads only; a constant number of queries per call. Rows are summed in Python with
:func:`.pnl.sale_pnl` — a 30-day window holds at most a few thousand sales.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

from pydantic import BaseModel, ConfigDict
from sqlalchemy import ColumnElement, Date, and_, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.cursor import decode_cursor, encode_cursor
from csmarket.modules.fx.api import FxSnapshot
from csmarket.modules.orders.api import TASHKENT, Days, window_start
from csmarket.modules.sales.models import PayoutRequest, Sale
from csmarket.modules.sales.pnl import PnlRow, ReconFlag, SalePnl, flag, sale_pnl
from csmarket.modules.sales.settings_store import read_sale_settings

_ZERO = Decimal(0)
_PERCENT = Decimal("0.1")
_REVERTED = ("rolled_back", "late_deposit")

#: When Skinslink completed the sale (see the module docstring).
DONE_AT = func.coalesce(Sale.credited_at, PayoutRequest.to_pay_at)


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True)


class PnlDay(_Frozen):
    day: date
    count: int
    income_usd: Decimal
    profit_usd: Decimal
    #: Income at the CBU rate minus the soʻm costs.
    profit_uzs: Decimal = _ZERO


class SalesPnl(_Frozen):
    """The window's totals (soʻm lines as in :class:`.pnl.SalePnl`)."""

    count: int
    income_usd: Decimal
    income_uzs: Decimal
    to_cards_uzs: Decimal
    to_balances_uzs: Decimal
    to_pay_uzs: Decimal
    withheld_uzs: Decimal
    bank_uzs: Decimal
    cost_uzs: Decimal
    cost_usd: Decimal
    profit_usd: Decimal
    #: Profit as a percent of income, one decimal; 0 without income.
    profit_percent: Decimal
    #: ``income_uzs − cost_uzs``.
    profit_uzs: Decimal
    by_day: list[PnlDay]


class ReconRow(_Frozen):
    number: str
    status: str
    done_at: datetime | None
    trade_id: int | None
    quoted_usd: Decimal
    amount_usd: Decimal | None
    flag: ReconFlag | None


class Recon(_Frozen):
    items: list[ReconRow]
    next_cursor: str | None
    expected_usd: Decimal
    credited_usd: Decimal
    problems: int


def _cbu_rate() -> ColumnElement[Decimal]:
    return (
        select(FxSnapshot.usd_uzs)
        .where(FxSnapshot.fetched_at <= Sale.created_at)
        .order_by(FxSnapshot.fetched_at.desc())
        .limit(1)
        .correlate(Sale)
        .scalar_subquery()
    )


def _row(sale: Sale, request: PayoutRequest | None, cbu: Decimal | None) -> PnlRow:
    return PnlRow(
        payout_to=sale.payout_to,
        status=sale.status,
        attention_reason=sale.attention_reason,
        quoted_usd=sale.quoted_usd,
        amount_usd=sale.amount_usd,
        items_uzs=sale.items_uzs,
        payout_uzs=sale.payout_uzs,
        rate=sale.rate,
        cbu_rate=cbu,
        request_status=request.status if request else None,
        request_amount_uzs=request.amount_uzs if request else None,
        request_fee_uzs=request.fee_uzs if request else None,
        request_bank_fee_uzs=request.bank_fee_uzs if request else None,
    )


def _total(lines: list[SalePnl]) -> dict[str, Decimal]:
    keys = (
        "income_usd",
        "income_uzs",
        "to_cards_uzs",
        "to_balances_uzs",
        "to_pay_uzs",
        "withheld_uzs",
        "bank_uzs",
        "cost_uzs",
        "cost_usd",
    )
    return {k: sum((getattr(p, k) for p in lines), _ZERO) for k in keys}


async def sales_pnl_between(db: AsyncSession, *, since: datetime, until: datetime) -> SalesPnl:
    """The skin-sales P&L of ``[since, until)``, one row per Tashkent day. Reads only."""
    pct = (await read_sale_settings(db)).bank_fee_pct
    day_of = cast(func.timezone("Asia/Tashkent", DONE_AT), Date)
    stmt = (
        select(Sale, PayoutRequest, _cbu_rate(), day_of)
        .outerjoin(PayoutRequest, PayoutRequest.sale_id == Sale.id)
        .where(since <= DONE_AT, until > DONE_AT)
    )
    per_day: dict[date, list[SalePnl]] = {}
    for sale, request, cbu, day in (await db.execute(stmt)).all():
        per_day.setdefault(day, []).append(sale_pnl(_row(sale, request, cbu), pct))
    first = since.astimezone(TASHKENT).date()
    last = (until - timedelta(microseconds=1)).astimezone(TASHKENT).date()
    return _summed(per_day, first, (last - first).days + 1)


async def sales_pnl(db: AsyncSession, *, days: Days, at: datetime) -> SalesPnl:
    """The skin-sales P&L of the ``days`` Tashkent days ending at ``at``. Reads only."""
    return await sales_pnl_between(
        db, since=window_start(at, days), until=at + timedelta(microseconds=1)
    )


def _summed(per_day: dict[date, list[SalePnl]], first: date, days: int) -> SalesPnl:
    every = [p for lines in per_day.values() for p in lines]
    total = _total(every)
    profit = total["income_usd"] - total["cost_usd"]
    income = total["income_usd"]
    by_day = []
    for n in range(days):
        day = first + timedelta(days=n)
        t = _total(per_day.get(day, []))
        by_day.append(
            PnlDay(
                day=day,
                count=len(per_day.get(day, [])),
                income_usd=t["income_usd"],
                profit_usd=t["income_usd"] - t["cost_usd"],
                profit_uzs=t["income_uzs"] - t["cost_uzs"],
            )
        )
    return SalesPnl(
        count=len(every),
        profit_usd=profit,
        profit_percent=(profit / income * 100).quantize(_PERCENT) if income else _ZERO,
        profit_uzs=total["income_uzs"] - total["cost_uzs"],
        by_day=by_day,
        **total,
    )


def _recon_where(since: datetime, at: datetime) -> ColumnElement[bool]:
    """Completed in the window, or an open revert whatever its date."""
    return or_(
        and_(DONE_AT.between(since, at)),
        and_(Sale.attention_reason.in_(_REVERTED), Sale.resolved_at.is_(None)),
    )


async def reconciliation(
    db: AsyncSession,
    *,
    days: Days,
    at: datetime,
    problems: bool,
    cursor: str | None,
    limit: int = 50,
) -> Recon:
    """Each sale's quoted vs credited USD, newest first; totals over the whole window."""
    since = window_start(at, days)
    stamp = func.coalesce(DONE_AT, Sale.updated_at)
    stmt = (
        select(Sale, PayoutRequest, DONE_AT, stamp)
        .outerjoin(PayoutRequest, PayoutRequest.sale_id == Sale.id)
        .where(_recon_where(since, at))
        .order_by(stamp.desc(), Sale.id.desc())
    )
    rows = []
    for sale, request, done, when in (await db.execute(stmt)).all():
        row = _row(sale, request, None)
        rows.append((sale, done, when, flag(row)))
    expected = sum((s.quoted_usd for s, *_ in rows), _ZERO)
    credited = sum((s.amount_usd or _ZERO for s, *_ in rows), _ZERO)
    flagged = sum(1 for *_, f in rows if f is not None)
    shown = [r for r in rows if r[3] is not None] if problems else rows
    if cursor is not None:
        c_at, c_id = decode_cursor(cursor)
        shown = [r for r in shown if (r[2], r[0].id) < (c_at, c_id)]
    page = shown[:limit]
    next_cursor = (
        encode_cursor(page[-1][2], page[-1][0].id) if len(shown) > limit and page else None
    )
    return Recon(
        items=[
            ReconRow(
                number=s.number,
                status=s.status,
                done_at=done,
                trade_id=s.trade_id,
                quoted_usd=s.quoted_usd,
                amount_usd=s.amount_usd,
                flag=f,
            )
            for s, done, _, f in page
        ],
        next_cursor=next_cursor,
        expected_usd=expected,
        credited_usd=credited,
        problems=flagged,
    )


__all__ = ["PnlDay", "Recon", "ReconRow", "SalesPnl", "reconciliation", "sales_pnl"]
