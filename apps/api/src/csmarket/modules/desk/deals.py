"""Deals: create, change, read, list (spec 2026-10-29-desk «The deal»).

A price recosts every **unresolved** item (``money.split_cost`` over all items' Skinslink
prices, so shares stay comparable); a resolved item keeps the cost its profit was booked
with. A deal whose items are all resolved closes itself (:func:`close_if_done`).
"""

from __future__ import annotations

import base64
import binascii
import json
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import Text, and_, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.clock import now
from csmarket.core.errors import ConflictError, NotFoundError, ValidationError
from csmarket.core.ids import new_id
from csmarket.modules.desk.models import RESOLVED, DeskDeal, DeskDeposit, DeskEntry, DeskItem
from csmarket.modules.desk.money import Currency, plain, split_cost, to_usd
from csmarket.modules.desk.schemas import (
    DealIn,
    DealOut,
    DealPatch,
    DealRowOut,
    DealsOut,
    DepositOut,
    ItemOut,
)
from csmarket.modules.users.api import parse_tradelink

#: Steam lets a trade be reversed for 7 days after it is accepted.
PROTECTION = timedelta(days=7)
PAGE = 50


def _link(raw: str | None) -> str | None:
    """A trade link checked for form; ``None`` stays ``None``.

    Raises:
        ValidationError: ``trade_link_invalid``.
    """
    return None if raw is None else parse_tradelink(raw).url


async def load_deal(db: AsyncSession, deal_id: str, *, lock: bool = False) -> DeskDeal:
    """The deal, optionally ``FOR UPDATE``.

    Raises:
        NotFoundError: ``deal_not_found``.
    """
    stmt = select(DeskDeal).where(cast(DeskDeal.id, Text) == deal_id)
    if lock:
        stmt = stmt.with_for_update()
    deal = await db.scalar(stmt)
    if deal is None:
        raise NotFoundError("no such deal", code="deal_not_found")
    return deal


async def items_of(db: AsyncSession, deal_id: str) -> list[DeskItem]:
    """A deal's items in the order they were added."""
    rows = await db.scalars(select(DeskItem).where(DeskItem.deal_id == deal_id))
    return sorted(rows.all(), key=lambda i: i.id)


def _price(deal: DeskDeal, items: list[DeskItem]) -> None:
    """Set ``paid_usd`` from the price and recost the unresolved items."""
    if deal.paid_amount is None or deal.paid_currency is None:
        deal.paid_usd = None
        return
    currency: Currency = "UZS" if deal.paid_currency == "UZS" else "USD"
    deal.paid_usd = to_usd(deal.paid_amount, currency, deal.rate)
    shares = split_cost(deal.paid_usd, [i.skinslink_usd for i in items])
    for item, share in zip(items, shares, strict=True):
        if item.state not in RESOLVED:
            item.cost_usd = share


async def create_deal(db: AsyncSession, body: DealIn) -> DeskDeal:
    """A new deal and its items; ``paid`` when it has a price, else ``agreed``.

    Raises:
        ValidationError: ``rate_required``, ``trade_link_invalid``.
    """
    deal = DeskDeal(
        id=new_id(),
        status="paid" if body.paid_amount is not None else "agreed",
        trader=body.trader.strip(),
        note=body.note,
        trade_link=_link(body.trade_link),
        paid_amount=body.paid_amount,
        paid_currency=body.paid_currency,
        rate=body.rate if body.paid_currency == "UZS" else None,
        method=body.method,
        paid_at=body.paid_at or (now() if body.paid_amount is not None else None),
    )
    items = [
        DeskItem(
            id=new_id(),
            deal_id=deal.id,
            name=i.name.strip(),
            asset_id=i.asset_id,
            image_url=i.image_url,
            skinslink_usd=i.skinslink_usd,
            destination=i.destination,
            state="open",
        )
        for i in body.items
    ]
    _price(deal, items)
    db.add(deal)
    await db.flush()
    db.add_all(items)
    await db.flush()
    return deal


async def update_deal(db: AsyncSession, deal_id: str, patch: DealPatch) -> DeskDeal:
    """Apply the fields ``patch`` sets.

    Raises:
        NotFoundError: ``deal_not_found``.
        ValidationError: ``rate_required``, ``trade_link_invalid``, ``price_incomplete``.
    """
    deal = await load_deal(db, deal_id, lock=True)
    fields = patch.model_fields_set
    for name in ("trader", "note", "method", "status"):
        if name not in fields:
            continue
        value = getattr(patch, name)
        if value is not None or name == "note":  # only the note may be cleared
            setattr(deal, name, value)
    if "trade_link" in fields:
        deal.trade_link = _link(patch.trade_link)
    if "guarantor_released" in fields and patch.guarantor_released is not None:
        deal.guarantor_released_at = now() if patch.guarantor_released else None
    if fields & {"paid_amount", "paid_currency", "rate"}:
        items = await items_of(db, deal.id)  # before the price changes: no autoflush mid-way
        if any(i.state in RESOLVED for i in items):
            raise ConflictError(
                "the price is locked once a skin is sold, credited or written off",
                code="price_locked",
            )
        if "paid_amount" in fields:
            deal.paid_amount = patch.paid_amount
            deal.paid_currency = patch.paid_currency
        if "rate" in fields:
            deal.rate = patch.rate
        if deal.paid_currency != "UZS":
            deal.rate = None
        if deal.paid_amount is not None and deal.status == "agreed":
            deal.status = "paid"
            deal.paid_at = deal.paid_at or now()
        _price(deal, items)
    if "paid_at" in fields and patch.paid_at is not None:
        deal.paid_at = patch.paid_at
    deal.updated_at = now()
    await db.flush()
    return deal


def require_price(deal: DeskDeal) -> None:
    """Nothing resolves before the deal has a price: each item's profit is measured against
    its share of it.

    Raises:
        ConflictError: ``price_required``.
    """
    if deal.paid_usd is None:
        raise ConflictError("set the deal's price first", code="price_required")


async def close_if_done(db: AsyncSession, deal: DeskDeal) -> None:
    """``closed`` once every item is resolved (a cancelled or reverted deal stays so)."""
    if deal.status in ("cancelled", "reverted", "closed"):
        return
    items = await items_of(db, deal.id)
    if items and all(i.state in RESOLVED for i in items):
        deal.status = "closed"
        deal.updated_at = now()
        await db.flush()


def item_out(i: DeskItem) -> ItemOut:
    """One item, money as strings."""
    return ItemOut(
        id=i.id,
        name=i.name,
        asset_id=i.asset_id,
        image_url=i.image_url,
        skinslink_usd=plain(i.skinslink_usd),
        destination="stock" if i.destination == "stock" else "skinslink",
        cost_usd=plain(i.cost_usd),
        state=i.state,
        deposit_id=i.deposit_id,
        sold_where=i.sold_where,
        sold_amount=plain(i.sold_amount),
        sold_currency="UZS" if i.sold_currency == "UZS" else "USD" if i.sold_currency else None,
        sold_usd=plain(i.sold_usd),
        resolved_at=i.resolved_at,
        note=i.note,
    )


def _deposit_out(d: DeskDeposit) -> DepositOut:
    return DepositOut(
        id=d.id,
        status=d.status,
        amount_usd=plain(d.amount_usd),
        amount_estimated=d.amount_estimated,
        trade_offer_id=d.trade_offer_id,
        offer_expiry_at=d.offer_expiry_at,
        hold_end_date=d.hold_end_date,
        fail_reason=d.fail_reason,
        accepted_at=d.accepted_at,
        credited_at=d.credited_at,
        reverted_at=d.reverted_at,
        created_at=d.created_at,
    )


async def _profit(db: AsyncSession, deal_id: str) -> Decimal:
    total = await db.scalar(
        select(func.coalesce(func.sum(DeskEntry.profit_usd), 0)).where(DeskEntry.deal_id == deal_id)
    )
    return Decimal(total or 0)


async def deal_out(db: AsyncSession, deal: DeskDeal) -> DealOut:
    """The deal page: the deal, items, deposits, protection end, profit so far."""
    await db.refresh(deal)
    items = await items_of(db, deal.id)
    deposits = list(
        (
            await db.scalars(
                select(DeskDeposit)
                .where(DeskDeposit.deal_id == deal.id)
                .order_by(DeskDeposit.created_at)
            )
        ).all()
    )
    accepted = [d.accepted_at for d in deposits if d.accepted_at and d.reverted_at is None]
    return DealOut(
        id=deal.id,
        status=deal.status,  # type: ignore[arg-type]  # the CHECK keeps it one of DealStatus
        trader=deal.trader,
        note=deal.note,
        trade_link=deal.trade_link,
        paid_amount=plain(deal.paid_amount),
        paid_currency=deal.paid_currency,  # type: ignore[arg-type]  # CHECK: UZS or USD
        rate=plain(deal.rate),
        paid_usd=plain(deal.paid_usd),
        method=deal.method,  # type: ignore[arg-type]  # CHECK: direct or guarantor
        paid_at=deal.paid_at,
        guarantor_released_at=deal.guarantor_released_at,
        created_at=deal.created_at,
        updated_at=deal.updated_at,
        items=[item_out(i) for i in items],
        deposits=[_deposit_out(d) for d in deposits],
        protected_until=max(accepted) + PROTECTION if accepted else None,
        profit_usd=plain(await _profit(db, deal.id)) or "0",
        resolved=bool(items) and all(i.state in RESOLVED for i in items),
    )


def _cursor(at: datetime, deal_id: str) -> str:
    raw = json.dumps([at.isoformat(), deal_id]).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _after(token: str) -> tuple[datetime, str]:
    try:
        stamp, deal_id = json.loads(base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)))
        return datetime.fromisoformat(stamp), str(deal_id)
    except (binascii.Error, ValueError, TypeError) as exc:
        raise ValidationError("invalid cursor", code="cursor") from exc


async def list_deals(
    db: AsyncSession, *, status: str | None, q: str | None, cursor: str | None
) -> DealsOut:
    """Newest first, :data:`PAGE` a page; ``q`` matches the trader."""
    stmt = select(DeskDeal)
    if status:
        stmt = stmt.where(DeskDeal.status == status)
    if q:
        escaped = q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        stmt = stmt.where(DeskDeal.trader.ilike(f"%{escaped}%", escape="\\"))
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
    counts: dict[str, tuple[int, int]] = {
        str(deal_id): (int(n), int(done))
        for deal_id, n, done in (
            await db.execute(
                select(
                    DeskItem.deal_id,
                    func.count(),
                    func.count().filter(DeskItem.state.in_(RESOLVED)),
                )
                .where(DeskItem.deal_id.in_(ids))
                .group_by(DeskItem.deal_id)
            )
        ).all()
    }
    profits: dict[str, Decimal] = {
        str(deal_id): Decimal(total)
        for deal_id, total in (
            await db.execute(
                select(DeskEntry.deal_id, func.sum(DeskEntry.profit_usd))
                .where(DeskEntry.deal_id.in_(ids))
                .group_by(DeskEntry.deal_id)
            )
        ).all()
    }
    rows = []
    for d in deals:
        n, done = counts.get(d.id, (0, 0))
        rows.append(
            DealRowOut(
                id=d.id,
                status=d.status,  # type: ignore[arg-type]  # CHECK keeps it a DealStatus
                trader=d.trader,
                method=d.method,  # type: ignore[arg-type]  # CHECK: direct or guarantor
                created_at=d.created_at,
                paid_amount=plain(d.paid_amount),
                paid_currency=d.paid_currency,  # type: ignore[arg-type]  # CHECK: UZS/USD
                paid_usd=plain(d.paid_usd),
                items=n,
                profit_usd=plain(profits.get(d.id, Decimal(0))) or "0",
                resolved=n > 0 and n == done,
            )
        )
    last = deals[-1] if deals else None
    return DealsOut(
        items=rows,
        next_cursor=_cursor(last.created_at, last.id) if more and last is not None else None,
    )


__all__ = [
    "PROTECTION",
    "close_if_done",
    "create_deal",
    "deal_out",
    "item_out",
    "items_of",
    "list_deals",
    "load_deal",
    "require_price",
    "update_deal",
]
