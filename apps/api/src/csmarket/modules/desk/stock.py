"""Items by hand: sell a stock skin, move an item, write one off; the stock list (spec
2026-10-29-desk «Stock and selling by hand»).

Each resolution books one ledger row (``desk_entries``) dated when it happened, then closes
the deal if every item is resolved.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import ColumnElement, Text, cast, select
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.clock import now
from csmarket.core.errors import ConflictError, NotFoundError
from csmarket.core.ids import new_id
from csmarket.core.logging import get_logger
from csmarket.modules.desk.deals import (
    close_if_done,
    item_out,
    load_deal,
    require_live,
    require_price,
)
from csmarket.modules.desk.inventory import refused, unavailable
from csmarket.modules.desk.models import DeskDeal, DeskEntry, DeskItem
from csmarket.modules.desk.money import plain, to_usd
from csmarket.modules.desk.schemas import MoveIn, SellIn, StockItemOut, StockOut, WriteOffIn
from csmarket.modules.skinslink.api import (
    DepositClient,
    SkinslinkError,
    SkinslinkUnavailableError,
)

log = get_logger("csmarket.desk.stock")


async def _open_item(db: AsyncSession, item_id: str) -> DeskItem:
    """The item ``FOR UPDATE``; it must be ``open``, its deal not cancelled.

    Raises:
        NotFoundError: ``item_not_found``.
        ConflictError: ``item_not_open``, ``deal_busy`` — the deal is cancelled.
    """
    item = await db.scalar(
        select(DeskItem).where(cast(DeskItem.id, Text) == item_id).with_for_update()
    )
    if item is None:
        raise NotFoundError("no such item", code="item_not_found")
    if item.state != "open":
        raise ConflictError("the item is not open", code="item_not_open")
    require_live(await load_deal(db, item.deal_id))
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
    require_price(await load_deal(db, item.deal_id))
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
    """Send an open item the other way (Skinslink ↔ stock).

    Raises:
        NotFoundError: ``item_not_found``.
        ConflictError: ``item_not_open``; ``no_asset`` — Skinslink takes a skin by its
            asset id, and this one has none.
    """
    item = await _open_item(db, item_id)
    if body.destination == "skinslink" and not item.asset_id:
        raise ConflictError("Skinslink needs the skin's asset id", code="no_asset")
    item.destination = body.destination
    await db.flush()
    return await load_deal(db, item.deal_id)


async def write_off(db: AsyncSession, item_id: str, body: WriteOffIn) -> DeskDeal:
    """Lost or given up: ``written_off`` and a loss of its cost."""
    item = await _open_item(db, item_id)
    require_price(await load_deal(db, item.deal_id))
    at = now()
    item.state = "written_off"
    item.note = body.note.strip()
    item.resolved_at = at
    db.add(_book(item, "write_off", -(item.cost_usd or Decimal(0)), at))
    deal = await load_deal(db, item.deal_id, lock=True)
    await db.flush()
    await close_if_done(db, deal)
    return deal


def _in_stock() -> tuple[ColumnElement[bool], ...]:
    """Open stock items of a deal that is not cancelled."""
    return (
        DeskItem.destination == "stock",
        DeskItem.state == "open",
        DeskDeal.status != "cancelled",
    )


async def list_stock(db: AsyncSession) -> StockOut:
    """The skins in the owner's stock, oldest first, with their cost (cancelled deals
    left out)."""
    rows = (
        await db.execute(
            select(DeskItem, DeskDeal)
            .join(DeskDeal, DeskDeal.id == DeskItem.deal_id)
            .where(*_in_stock())
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


#: Skinslink ``get-prices`` takes at most this many names.
MAX_NAMES = 2000


async def stock_prices(db: AsyncSession, client: DepositClient) -> dict[str, str]:
    """What Skinslink pays now for each stock skin, by market name (``get-prices``, price
    only). The names are read and the session committed before the one call, so no
    connection is held across it; names Skinslink does not take are left out.

    Raises:
        DeskUnavailableError: ``desk_unavailable``.
    """
    names = (
        await db.scalars(
            select(DeskItem.name)
            .join(DeskDeal, DeskDeal.id == DeskItem.deal_id)
            .where(*_in_stock())
            .order_by(DeskDeal.created_at, DeskItem.id)
        )
    ).all()
    await db.commit()
    unique = list(dict.fromkeys(names))[:MAX_NAMES]
    if not unique:
        return {}
    try:
        quotes = await client.get_prices(unique)
    except SkinslinkError as exc:
        raise refused(exc) from None
    except SkinslinkUnavailableError as exc:
        log.warning("desk.skinslink.unavailable", error=type(exc).__name__)
        raise unavailable() from None
    return {q.name: plain(q.price_usd) or "0" for q in quotes}


__all__ = ["MAX_NAMES", "list_stock", "move", "sell", "stock_prices", "write_off"]
