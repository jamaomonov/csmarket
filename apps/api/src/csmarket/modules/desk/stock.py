"""Items by hand: sell a stock skin, move an item, write one off; the stock list (spec
2026-10-29-desk «Stock and selling by hand»).

Each resolution books one ledger row (``desk_entries``) dated when it happened, then closes
the deal if every item is resolved.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import Text, cast, select
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.clock import now
from csmarket.core.errors import ConflictError, NotFoundError
from csmarket.core.ids import new_id
from csmarket.modules.desk.deals import close_if_done, item_out, load_deal
from csmarket.modules.desk.models import DeskDeal, DeskEntry, DeskItem
from csmarket.modules.desk.money import plain, to_usd
from csmarket.modules.desk.schemas import MoveIn, SellIn, StockItemOut, StockOut, WriteOffIn


async def _open_item(db: AsyncSession, item_id: str) -> DeskItem:
    """The item ``FOR UPDATE``; it must be ``open``.

    Raises:
        NotFoundError: ``item_not_found``.
        ConflictError: ``item_not_open``.
    """
    item = await db.scalar(
        select(DeskItem).where(cast(DeskItem.id, Text) == item_id).with_for_update()
    )
    if item is None:
        raise NotFoundError("no such item", code="item_not_found")
    if item.state != "open":
        raise ConflictError("the item is not open", code="item_not_open")
    return item


def _book(item: DeskItem, kind: str, profit: Decimal, at: datetime) -> DeskEntry:
    return DeskEntry(
        id=new_id(), deal_id=item.deal_id, item_id=item.id, kind=kind, profit_usd=profit, at=at
    )


async def sell(db: AsyncSession, item_id: str, body: SellIn) -> DeskDeal:
    """A stock skin sold by hand: ``sold`` and a ``sale`` row of ``sold_usd − cost_usd``.

    Raises:
        NotFoundError: ``item_not_found``.
        ConflictError: ``item_not_open`` (also a Skinslink-bound item).
        ValidationError: ``rate_required``.
    """
    item = await _open_item(db, item_id)
    if item.destination != "stock":
        raise ConflictError("only a stock item is sold by hand", code="item_not_open")
    at = body.at or now()
    item.sold_where = body.where.strip()
    item.sold_amount = body.amount
    item.sold_currency = body.currency
    item.sold_rate = body.rate if body.currency == "UZS" else None
    item.sold_usd = to_usd(body.amount, body.currency, body.rate)
    item.state = "sold"
    item.resolved_at = at
    db.add(_book(item, "sale", item.sold_usd - (item.cost_usd or Decimal(0)), at))
    deal = await load_deal(db, item.deal_id, lock=True)
    await db.flush()
    await close_if_done(db, deal)
    return deal


async def move(db: AsyncSession, item_id: str, body: MoveIn) -> DeskDeal:
    """Send an open item the other way (Skinslink ↔ stock)."""
    item = await _open_item(db, item_id)
    item.destination = body.destination
    await db.flush()
    return await load_deal(db, item.deal_id)


async def write_off(db: AsyncSession, item_id: str, body: WriteOffIn) -> DeskDeal:
    """Lost or given up: ``written_off`` and a loss of its cost."""
    item = await _open_item(db, item_id)
    at = now()
    item.state = "written_off"
    item.note = body.note.strip()
    item.resolved_at = at
    db.add(_book(item, "write_off", -(item.cost_usd or Decimal(0)), at))
    deal = await load_deal(db, item.deal_id, lock=True)
    await db.flush()
    await close_if_done(db, deal)
    return deal


async def list_stock(db: AsyncSession) -> StockOut:
    """The skins in the owner's stock, oldest first, with their cost."""
    rows = (
        await db.execute(
            select(DeskItem, DeskDeal)
            .join(DeskDeal, DeskDeal.id == DeskItem.deal_id)
            .where(DeskItem.destination == "stock", DeskItem.state == "open")
            .order_by(DeskDeal.created_at, DeskItem.id)
        )
    ).all()
    items = [
        StockItemOut(
            **item_out(i).model_dump(), deal_id=d.id, trader=d.trader, bought_at=d.created_at
        )
        for i, d in rows
    ]
    total = sum((i.cost_usd or Decimal(0) for i, _ in rows), Decimal(0))
    return StockOut(items=items, total_cost_usd=plain(total) or "0")


__all__ = ["list_stock", "move", "sell", "write_off"]
