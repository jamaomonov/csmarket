"""Deals: create, change, read (spec 2026-10-29-desk «The deal», 2026-10-31-desk-v2).

A price recosts every **unresolved** item (``money.split_cost`` over all items' Skinslink
prices, so shares stay comparable); a resolved item keeps the cost its profit was booked
with. A deal whose items are all resolved settles itself (:func:`close_if_done`): ``closed``,
or ``reverted`` when any of its items was reverted.

The owner sets ``agreed`` / ``paid`` / ``received`` / ``cancelled`` by hand; ``cancelled``
only while nothing of the deal is with Skinslink or resolved (``deal_busy``), and a settled
deal's status is the system's.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import Text, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.clock import now
from csmarket.core.config import get_settings
from csmarket.core.errors import ConflictError, NotFoundError
from csmarket.core.ids import new_id
from csmarket.modules.desk.models import (
    DEPOSIT_OPEN,
    RESOLVED,
    DeskDeal,
    DeskDeposit,
    DeskEntry,
    DeskItem,
)
from csmarket.modules.desk.money import Currency, plain, split_cost, to_usd
from csmarket.modules.desk.schemas import DealIn, DealOut, DealPatch, DepositOut, ItemIn, ItemOut
from csmarket.modules.skins.api import images_by_name, steam_image
from csmarket.modules.users.api import parse_tradelink

#: Steam lets a trade be reversed for 7 days after it is accepted.
PROTECTION = timedelta(days=7)
#: Statuses only the system sets.
SETTLED = ("closed", "reverted")


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


def recost(deal: DeskDeal, items: list[DeskItem]) -> None:
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


def picture(url: str | None) -> str | None:
    """A stored picture as the admin loads it (a Steam CDN host our side can reach)."""
    return steam_image(url, host=get_settings().skins_image_host)


async def fill_images(db: AsyncSession, items: Iterable[DeskItem]) -> None:
    """Our catalogue's picture for each item that has none (by market name, phase ignored)."""
    bare = [i for i in items if not i.image_url]
    found = await images_by_name(db, (i.name for i in bare))
    for item in bare:
        item.image_url = found.get(item.name)


def new_items(deal_id: str, body: Iterable[ItemIn]) -> list[DeskItem]:
    """Rows for ``body``, ``open``."""
    return [
        DeskItem(
            id=new_id(),
            deal_id=deal_id,
            name=i.name.strip(),
            asset_id=i.asset_id,
            image_url=i.image_url,
            skinslink_usd=i.skinslink_usd,
            destination=i.destination,
            state="open",
        )
        for i in body
    ]


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
        guarantor=body.guarantor.strip() if body.guarantor else None,
        paid_at=body.paid_at or (now() if body.paid_amount is not None else None),
    )
    items = new_items(deal.id, body.items)
    await fill_images(db, items)
    recost(deal, items)
    db.add(deal)
    await db.flush()
    db.add_all(items)
    await db.flush()
    return deal


def _plain_fields(deal: DeskDeal, patch: DealPatch) -> None:
    """Trader, note, method, guarantor as set; only the note and the guarantor may be cleared."""
    for name in ("trader", "note", "method", "guarantor"):
        if name not in patch.model_fields_set:
            continue
        value = getattr(patch, name)
        if value is not None or name in ("note", "guarantor"):
            setattr(deal, name, value.strip() if name == "guarantor" and value else value)


async def update_deal(db: AsyncSession, deal_id: str, patch: DealPatch) -> DeskDeal:
    """Apply the fields ``patch`` sets.

    Raises:
        NotFoundError: ``deal_not_found``.
        ConflictError: ``deal_busy``, ``price_locked``.
        ValidationError: ``rate_required``, ``trade_link_invalid``, ``price_incomplete``.
    """
    deal = await load_deal(db, deal_id, lock=True)
    fields = patch.model_fields_set
    _plain_fields(deal, patch)
    if "status" in fields and patch.status is not None:
        await _set_status(db, deal, patch.status)
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
        recost(deal, items)
    if "paid_at" in fields and patch.paid_at is not None:
        deal.paid_at = patch.paid_at
    deal.updated_at = now()
    await db.flush()
    return deal


def _busy() -> ConflictError:
    return ConflictError("the deal has skins with Skinslink or resolved", code="deal_busy")


async def _set_status(db: AsyncSession, deal: DeskDeal, status: str) -> None:
    """A hand-set status (spec 2026-10-31-desk-v2, bug 2).

    Raises:
        ConflictError: ``deal_busy`` — a settled deal, or cancelling one with an open
            deposit or a skin sent or resolved.
    """
    if status == deal.status:
        return
    if deal.status in SETTLED:
        raise _busy()
    if status == "cancelled":
        moving = await db.scalar(
            select(func.count()).where(DeskItem.deal_id == deal.id, DeskItem.state != "open")
        )
        open_deposit = await db.scalar(
            select(func.count()).where(
                DeskDeposit.deal_id == deal.id, DeskDeposit.status.in_(DEPOSIT_OPEN)
            )
        )
        if moving or open_deposit:
            raise _busy()
    deal.status = status


def require_live(deal: DeskDeal) -> None:
    """A cancelled deal is frozen: nothing of it is sent, sold, written off, moved or added.

    Raises:
        ConflictError: ``deal_busy``.
    """
    if deal.status == "cancelled":
        raise ConflictError("the deal is cancelled", code="deal_busy")


#: Item states still on their way to Skinslink: their profit is not booked yet.
PENDING = ("open", "sent")


def expected_profit(deal: DeskDeal, items: Iterable[DeskItem], booked: Decimal) -> Decimal | None:
    """The profit booked so far plus, for each skin still bound for Skinslink (``open`` /
    ``sent``), its Skinslink price less its cost.

    ``None`` for a cancelled deal, one without a price, or when no priced skin is left
    for Skinslink (an unpriced one makes the figure unknown).
    """
    if deal.status == "cancelled" or deal.paid_usd is None:
        return None
    pending = [i for i in items if i.destination == "skinslink" and i.state in PENDING]
    if not pending:
        return None
    total = booked
    for i in pending:
        if i.skinslink_usd is None or i.cost_usd is None:
            return None
        total += i.skinslink_usd - i.cost_usd
    return total


def require_price(deal: DeskDeal) -> None:
    """Nothing resolves before the deal has a price: each item's profit is measured against
    its share of it.

    Raises:
        ConflictError: ``price_required``.
    """
    if deal.paid_usd is None:
        raise ConflictError("set the deal's price first", code="price_required")


async def close_if_done(db: AsyncSession, deal: DeskDeal) -> None:
    """Once every item is resolved: ``reverted`` if any item was reverted, else ``closed``
    (a cancelled deal stays so)."""
    if deal.status == "cancelled":
        return
    items = await items_of(db, deal.id)
    if not items or not all(i.state in RESOLVED for i in items):
        return
    target = "reverted" if any(i.state == "reverted" for i in items) else "closed"
    if deal.status != target:
        deal.status = target
        deal.updated_at = now()
        await db.flush()


def item_out(i: DeskItem) -> ItemOut:
    """One item, money as strings."""
    return ItemOut(
        id=i.id,
        name=i.name,
        asset_id=i.asset_id,
        image_url=picture(i.image_url),
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
        bot_name=d.bot_name,
        bot_steam_id=d.bot_steam_id,
        bot_persona=d.bot_persona,
        bot_avatar_url=d.bot_avatar_url or None,  # "": Steam had none
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
    booked = await _profit(db, deal.id)
    expected = expected_profit(deal, items, booked)
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
        guarantor=deal.guarantor,
        paid_at=deal.paid_at,
        guarantor_released_at=deal.guarantor_released_at,
        created_at=deal.created_at,
        updated_at=deal.updated_at,
        items=[item_out(i) for i in items],
        deposits=[_deposit_out(d) for d in deposits],
        protected_until=max(accepted) + PROTECTION if accepted else None,
        profit_usd=plain(booked) or "0",
        expected_profit_usd=plain(expected),
        resolved=bool(items) and all(i.state in RESOLVED for i in items),
    )


__all__ = [
    "PROTECTION",
    "SETTLED",
    "close_if_done",
    "create_deal",
    "deal_out",
    "expected_profit",
    "fill_images",
    "item_out",
    "items_of",
    "load_deal",
    "new_items",
    "picture",
    "recost",
    "require_live",
    "require_price",
    "update_deal",
]
