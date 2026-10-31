"""The deals list and the traders (spec 2026-10-29-desk, 2026-10-31-desk-v2 «The list»,
stage 2 «Traders»).

A row tells deals with the same trader apart: the dearest skin and its picture, the
Skinslink value, the note, the protection end. ``q`` matches the trader or an item name.
Traders group deals by ``lower(trader)``; trader names and trade links are never logged.
"""

from __future__ import annotations

import base64
import binascii
import json
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    ColumnElement,
    Text,
    and_,
    cast,
    exists,
    func,
    or_,
    select,
)
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import QueryableAttribute

from csmarket.core.errors import ValidationError
from csmarket.modules.desk.deals import PROTECTION, expected_profit, picture
from csmarket.modules.desk.models import RESOLVED, DeskDeal, DeskDeposit, DeskEntry, DeskItem
from csmarket.modules.desk.money import plain
from csmarket.modules.desk.schemas import (
    DealRowOut,
    DealsOut,
    FirstItemOut,
    TraderOut,
    TradersOut,
)

PAGE = 50
#: The most traders one answer lists.
TRADERS = 50


def _cursor(at: datetime, deal_id: str) -> str:
    raw = json.dumps([at.isoformat(), deal_id]).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _after(token: str) -> tuple[datetime, str]:
    try:
        stamp, deal_id = json.loads(base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)))
        return datetime.fromisoformat(stamp), str(deal_id)
    except (binascii.Error, ValueError, TypeError) as exc:
        raise ValidationError("invalid cursor", code="cursor") from exc


def _like(q: str) -> str:
    escaped = q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


async def _profits(db: AsyncSession, ids: list[str]) -> dict[str, Decimal]:
    rows = await db.execute(
        select(DeskEntry.deal_id, func.sum(DeskEntry.profit_usd))
        .where(DeskEntry.deal_id.in_(ids))
        .group_by(DeskEntry.deal_id)
    )
    return {str(deal_id): Decimal(total) for deal_id, total in rows.all()}


@dataclass
class _Items:
    n: int = 0
    done: int = 0
    priced: Decimal | None = None
    first: DeskItem | None = None
    rows: list[DeskItem] = field(default_factory=list)


def _dearer(a: DeskItem | None, b: DeskItem) -> bool:
    """``b`` is dearer than ``a`` (an unpriced item loses; a tie keeps the first added)."""
    if a is None:
        return True
    return (b.skinslink_usd or Decimal(-1)) > (a.skinslink_usd or Decimal(-1))


async def _items(db: AsyncSession, ids: list[str]) -> dict[str, _Items]:
    rows = await db.scalars(select(DeskItem).where(DeskItem.deal_id.in_(ids)))
    out: dict[str, _Items] = {}
    for item in sorted(rows.all(), key=lambda i: i.id):
        agg = out.setdefault(item.deal_id, _Items())
        agg.n += 1
        agg.rows.append(item)
        agg.done += item.state in RESOLVED
        if item.skinslink_usd is not None:
            agg.priced = (agg.priced or Decimal(0)) + item.skinslink_usd
        if _dearer(agg.first, item):
            agg.first = item
    return out


async def _protected(db: AsyncSession, ids: list[str]) -> dict[str, datetime]:
    rows = await db.execute(
        select(DeskDeposit.deal_id, func.max(DeskDeposit.accepted_at))
        .where(
            DeskDeposit.deal_id.in_(ids),
            DeskDeposit.accepted_at.is_not(None),
            DeskDeposit.reverted_at.is_(None),
        )
        .group_by(DeskDeposit.deal_id)
    )
    out: dict[str, datetime] = {}
    for deal_id, at in rows.all():
        if isinstance(at, datetime):  # ``max()`` of a timestamp column; never NULL here
            out[str(deal_id)] = at + PROTECTION
    return out


def _row(d: DeskDeal, agg: _Items, profit: Decimal, protected: datetime | None) -> DealRowOut:
    first = agg.first
    return DealRowOut(
        id=d.id,
        status=d.status,  # type: ignore[arg-type]  # CHECK keeps it a DealStatus
        trader=d.trader,
        method=d.method,  # type: ignore[arg-type]  # CHECK: direct or guarantor
        guarantor=d.guarantor,
        note=d.note,
        created_at=d.created_at,
        paid_amount=plain(d.paid_amount),
        paid_currency=d.paid_currency,  # type: ignore[arg-type]  # CHECK: UZS/USD
        paid_usd=plain(d.paid_usd),
        items=agg.n,
        first_item=None
        if first is None
        else FirstItemOut(name=first.name, image_url=picture(first.image_url)),
        skinslink_usd=plain(agg.priced),
        profit_usd=plain(profit) or "0",
        expected_profit_usd=plain(expected_profit(d, agg.rows, profit)),
        resolved=agg.n > 0 and agg.n == agg.done,
        protected_until=protected,
        guarantor_released_at=d.guarantor_released_at,
    )


async def list_deals(
    db: AsyncSession, *, status: str | None, q: str | None, cursor: str | None
) -> DealsOut:
    """Newest first, :data:`PAGE` a page; ``q`` matches the trader or an item's name."""
    stmt = select(DeskDeal)
    if status:
        stmt = stmt.where(DeskDeal.status == status)
    if q and q.strip():
        like = _like(q)
        stmt = stmt.where(
            or_(
                DeskDeal.trader.ilike(like, escape="\\"),
                exists().where(
                    DeskItem.deal_id == DeskDeal.id, DeskItem.name.ilike(like, escape="\\")
                ),
            )
        )
    if cursor:
        at, last_id = _after(cursor)
        stmt = stmt.where(
            or_(
                DeskDeal.created_at < at,
                and_(DeskDeal.created_at == at, cast(DeskDeal.id, Text) < last_id),
            )
        )
    deals = list(
        (
            await db.scalars(
                stmt.order_by(DeskDeal.created_at.desc(), DeskDeal.id.desc()).limit(PAGE + 1)
            )
        ).all()
    )
    more = len(deals) > PAGE
    deals = deals[:PAGE]
    ids = [d.id for d in deals]
    items, profits, protected = (
        await _items(db, ids),
        await _profits(db, ids),
        await _protected(db, ids),
    )
    rows = [
        _row(d, items.get(d.id, _Items()), profits.get(d.id, Decimal(0)), protected.get(d.id))
        for d in deals
    ]
    last = deals[-1] if deals else None
    return DealsOut(
        items=rows,
        next_cursor=_cursor(last.created_at, last.id) if more and last is not None else None,
    )


def _trader_key() -> ColumnElement[str]:
    return func.lower(func.trim(DeskDeal.trader))


async def _newest(
    db: AsyncSession,
    column: QueryableAttribute[str | None],
    keys: list[str],
    *where: ColumnElement[bool],
) -> dict[str, str]:
    """``column`` of each group's newest deal (matching ``where``), by group key."""
    k = _trader_key()
    rows = await db.execute(
        select(k, column)
        .ext(distinct_on(k))
        .where(k.in_(keys), *where)
        .order_by(k, DeskDeal.created_at.desc(), DeskDeal.id.desc())
    )
    return {str(g): str(v) for g, v in rows.all()}


async def _per_trader(
    db: AsyncSession,
    value: ColumnElement[Decimal] | ColumnElement[int],
    keys: list[str],
    *where: ColumnElement[bool],
) -> dict[str, Decimal]:
    """``value`` over the ledger rows of each group's live deals, by group key."""
    k = _trader_key()
    rows = await db.execute(
        select(k, value)
        .join(DeskDeal, DeskDeal.id == DeskEntry.deal_id)
        .where(k.in_(keys), DeskDeal.status != "cancelled", *where)
        .group_by(k)
    )
    return {str(g): Decimal(str(v or 0)) for g, v in rows.all()}


async def traders(db: AsyncSession, q: str | None) -> TradersOut:
    """Deals grouped by ``lower(trader)`` in SQL, the latest first, :data:`TRADERS` at most.

    Counts and sums leave out cancelled deals; the name and trade link are the newest deal's
    (a cancelled one included — it still names the trader).
    """
    k = _trader_key()
    live = DeskDeal.status != "cancelled"
    last_at = func.max(DeskDeal.created_at)
    stmt = (
        select(
            k,
            last_at,
            func.count().filter(live),
            func.coalesce(func.sum(DeskDeal.paid_usd).filter(live), 0),
        )
        .group_by(k)
        .order_by(last_at.desc(), k)
        .limit(TRADERS)
    )
    if q and q.strip():
        stmt = stmt.where(DeskDeal.trader.ilike(_like(q), escape="\\"))
    groups = (await db.execute(stmt)).all()
    keys = [str(g[0]) for g in groups]
    names = await _newest(db, DeskDeal.trader, keys)
    links = await _newest(db, DeskDeal.trade_link, keys, DeskDeal.trade_link.is_not(None))
    profits = await _per_trader(db, func.sum(DeskEntry.profit_usd), keys)
    reverts = await _per_trader(
        db, func.count(func.distinct(DeskEntry.deal_id)), keys, DeskEntry.kind == "revert"
    )
    return TradersOut(
        items=[
            TraderOut(
                trader=names[key],
                deals=int(deals),
                paid_usd=plain(Decimal(paid or 0)) or "0",
                profit_usd=plain(profits.get(key, Decimal(0))) or "0",
                reverts=int(reverts.get(key, Decimal(0))),
                last_trade_link=links.get(key),
                last_deal_at=at,
            )
            for key, (_, at, deals, paid) in zip(keys, groups, strict=True)
        ]
    )


__all__ = ["PAGE", "TRADERS", "list_deals", "traders"]
