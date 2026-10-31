"""``/api/v1/admin/desk/*`` — «Мои сделки», the owner's own (specs 2026-10-29-desk,
2026-10-31-desk-v2).

Every route needs ``admin`` and ``desk`` (``require_desk``). Writes take ``Idempotency-Key``
and replay with ``replayed`` / ``remember``; ``POST /inventory`` and ``POST /stock/prices``
are keyless — they only read from Skinslink and write nothing.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.api.v1.deps import db_session
from csmarket.core.config import get_settings
from csmarket.core.redis import get_redis
from csmarket.modules.admin.api import remember, replayed, require_desk, required_key
from csmarket.modules.desk import deals, deposits, items, listing, stock, summary
from csmarket.modules.desk.inventory import load_inventory
from csmarket.modules.desk.money import plain
from csmarket.modules.desk.schemas import (
    DealIn,
    DealOut,
    DealPatch,
    DealsOut,
    DealStatus,
    DepositIn,
    InventoryIn,
    InventoryOut,
    ItemsIn,
    MoveIn,
    RateOut,
    SellIn,
    StockOut,
    SummaryOut,
    TradersOut,
    WithdrawalIn,
    WithdrawalOut,
    WithdrawalsOut,
    WriteOffIn,
)
from csmarket.modules.fx.api import current_usd_uzs
from csmarket.modules.sales.api import inventory_client
from csmarket.modules.skinslink.api import DepositClient
from csmarket.modules.users.api import User

router = APIRouter(prefix="/admin/desk", tags=["admin"], dependencies=[Depends(require_desk)])

Db = Annotated[AsyncSession, Depends(db_session, scope="function")]
Key = Annotated[str, Depends(required_key)]
Client = Annotated[DepositClient, Depends(inventory_client)]
Owner = Annotated[User, Depends(require_desk)]


async def _keyed(
    db: AsyncSession, *, scope: str, key: str, asked: dict[str, Any], run: Any
) -> dict[str, Any]:
    """Replay ``key`` or run the write, remember its answer and commit."""
    if (hit := await replayed(db, scope=scope, key=key, request=asked)) is not None:
        return hit
    out: dict[str, Any] = (await run()).model_dump(mode="json")
    await remember(db, scope=scope, key=key, request=asked, response=out)
    await db.commit()
    return out


@router.post("/inventory", response_model=InventoryOut, summary="A trader's inventory")
async def post_inventory(body: InventoryIn, db: Db, client: Client) -> InventoryOut:
    """What Skinslink takes from a trade link's inventory now, with prices and our pictures.

    Keyless: it writes nothing anywhere.
    """
    return await load_inventory(db, client, body.trade_link)


@router.get("/rate", response_model=RateOut, summary="The CBU rate")
async def get_rate(db: Db) -> RateOut:
    """The CBU rate (no uplift) a soʻm price is converted at by default."""
    fx = await current_usd_uzs(
        db, get_redis(), max_age_days=get_settings().fx_max_age_days, uplift_pct=Decimal(0)
    )
    return RateOut(usd_uzs=None if fx is None else plain(fx.rate))


@router.post("/deals", response_model=DealOut, status_code=201, summary="A new deal")
async def post_deal(body: DealIn, db: Db, key: Key) -> DealOut:
    """A deal with its items and, if given, its price."""

    async def run() -> DealOut:
        return await deals.deal_out(db, await deals.create_deal(db, body))

    asked = body.model_dump(mode="json")
    return DealOut.model_validate(
        await _keyed(db, scope="admin.desk.deal.create", key=key, asked=asked, run=run)
    )


@router.get("/deals", response_model=DealsOut, summary="Deals")
async def get_deals(
    db: Db,
    status: DealStatus | None = None,
    q: Annotated[str | None, Query(max_length=120)] = None,
    cursor: Annotated[str | None, Query(max_length=300)] = None,
) -> DealsOut:
    """Newest first, 50 a page; ``q`` matches the trader or an item's name."""
    return await listing.list_deals(db, status=status, q=q, cursor=cursor)


@router.get("/traders", response_model=TradersOut, summary="Traders")
async def get_traders(db: Db, q: Annotated[str | None, Query(max_length=120)] = None) -> TradersOut:
    """Deals grouped by trader (case ignored): deals, paid, profit, reverts, the last link."""
    return await listing.traders(db, q)


@router.get("/deals/{deal_id}", response_model=DealOut, summary="A deal")
async def get_deal(deal_id: str, db: Db) -> DealOut:
    """The deal page."""
    return await deals.deal_out(db, await deals.load_deal(db, deal_id))


@router.patch("/deals/{deal_id}", response_model=DealOut, summary="Change a deal")
async def patch_deal(deal_id: str, body: DealPatch, db: Db, key: Key) -> DealOut:
    """Any of the deal's fields; a new price recosts the unresolved items."""

    async def run() -> DealOut:
        return await deals.deal_out(db, await deals.update_deal(db, deal_id, body))

    asked = {"deal_id": deal_id, **body.model_dump(mode="json", exclude_unset=True)}
    return DealOut.model_validate(
        await _keyed(db, scope="admin.desk.deal.update", key=key, asked=asked, run=run)
    )


@router.post("/deals/{deal_id}/items", response_model=DealOut, summary="Add skins")
async def post_items(deal_id: str, body: ItemsIn, db: Db, key: Key) -> DealOut:
    """More skins for the deal; the price is split again (``price_locked`` once one resolved)."""

    async def run() -> DealOut:
        return await deals.deal_out(db, await items.add_items(db, deal_id, body))

    asked = {"deal_id": deal_id, **body.model_dump(mode="json")}
    return DealOut.model_validate(
        await _keyed(db, scope="admin.desk.items.add", key=key, asked=asked, run=run)
    )


@router.post("/deals/{deal_id}/deposit", response_model=DealOut, summary="Send to Skinslink")
async def post_deposit(
    deal_id: str, db: Db, key: Key, client: Client, body: DepositIn | None = None
) -> DealOut:
    """«Отправить обмен»: a Skinslink bot offers the trader a trade for the deal's skins —
    only ``item_ids`` when given.

    The deposit is committed before the one Skinslink call; a lost answer is left to the poll.
    """
    item_ids = body.item_ids if body is not None else None
    asked: dict[str, Any] = {"deal_id": deal_id}
    if item_ids is not None:
        asked["item_ids"] = item_ids
    scope = "admin.desk.deposit"
    if (hit := await replayed(db, scope=scope, key=key, request=asked)) is not None:
        return DealOut.model_validate(hit)
    out = await deals.deal_out(db, await deposits.send(db, client, deal_id, item_ids))
    await remember(db, scope=scope, key=key, request=asked, response=out.model_dump(mode="json"))
    await db.commit()
    return out


@router.post("/items/{item_id}/sell", response_model=DealOut, summary="Sold from stock")
async def post_sell(item_id: str, body: SellIn, db: Db, key: Key) -> DealOut:
    """A stock skin sold by hand: where, how much."""

    async def run() -> DealOut:
        return await deals.deal_out(db, await stock.sell(db, item_id, body))

    asked = {"item_id": item_id, **body.model_dump(mode="json")}
    return DealOut.model_validate(
        await _keyed(db, scope="admin.desk.item.sell", key=key, asked=asked, run=run)
    )


@router.post("/items/{item_id}/move", response_model=DealOut, summary="Skinslink ↔ stock")
async def post_move(item_id: str, body: MoveIn, db: Db, key: Key) -> DealOut:
    """Send an open item the other way."""

    async def run() -> DealOut:
        return await deals.deal_out(db, await stock.move(db, item_id, body))

    asked = {"item_id": item_id, **body.model_dump(mode="json")}
    return DealOut.model_validate(
        await _keyed(db, scope="admin.desk.item.move", key=key, asked=asked, run=run)
    )


@router.post("/items/{item_id}/write-off", response_model=DealOut, summary="Write off")
async def post_write_off(item_id: str, body: WriteOffIn, db: Db, key: Key) -> DealOut:
    """Lost or given up: a loss of its cost."""

    async def run() -> DealOut:
        return await deals.deal_out(db, await stock.write_off(db, item_id, body))

    asked = {"item_id": item_id, **body.model_dump(mode="json")}
    return DealOut.model_validate(
        await _keyed(db, scope="admin.desk.item.write_off", key=key, asked=asked, run=run)
    )


@router.delete("/items/{item_id}", response_model=DealOut, summary="Remove a skin")
async def delete_item(item_id: str, db: Db, key: Key) -> DealOut:
    """An open skin off its deal; the price is split again over the rest."""

    async def run() -> DealOut:
        return await deals.deal_out(db, await items.delete_item(db, item_id))

    return DealOut.model_validate(
        await _keyed(
            db, scope="admin.desk.item.delete", key=key, asked={"item_id": item_id}, run=run
        )
    )


@router.post("/items/{item_id}/undo", response_model=DealOut, summary="Undo a sale or write-off")
async def post_undo(item_id: str, db: Db, key: Key, owner: Owner) -> DealOut:
    """A sold or written-off skin back to open; its ledger row is deleted (audited)."""

    async def run() -> DealOut:
        return await deals.deal_out(db, await items.undo(db, item_id, actor_id=owner.id))

    return DealOut.model_validate(
        await _keyed(db, scope="admin.desk.item.undo", key=key, asked={"item_id": item_id}, run=run)
    )


@router.get("/stock", response_model=StockOut, summary="My stock")
async def get_stock(db: Db) -> StockOut:
    """Skins in the owner's own Steam account, with their cost."""
    return await stock.list_stock(db)


@router.post("/stock/prices", response_model=dict[str, str], summary="Stock at Skinslink")
async def post_stock_prices(db: Db, client: Client) -> dict[str, str]:
    """What Skinslink pays now for each stock skin: ``{market name: price_usd}``; names it
    does not take are left out.

    Keyless: it only reads Skinslink ``get-prices`` and writes nothing.
    """
    return await stock.stock_prices(db, client)


@router.get("/summary", response_model=SummaryOut, summary="My figures")
async def get_summary(
    db: Db,
    start: Annotated[date | None, Query(alias="from")] = None,
    end: Annotated[date | None, Query(alias="to")] = None,
) -> SummaryOut:
    """Profit and revenue in the window (Tashkent days), in transit, stock, the share."""
    return await summary.summary(db, start, end)


@router.post("/withdrawals", response_model=WithdrawalOut, status_code=201, summary="Took out")
async def post_withdrawal(body: WithdrawalIn, db: Db, key: Key) -> WithdrawalOut:
    """«Вывел себе»: the Skinslink share drops."""

    async def run() -> WithdrawalOut:
        return await summary.add_withdrawal(db, body)

    asked = body.model_dump(mode="json")
    return WithdrawalOut.model_validate(
        await _keyed(db, scope="admin.desk.withdrawal", key=key, asked=asked, run=run)
    )


@router.get("/withdrawals", response_model=WithdrawalsOut, summary="What I took out")
async def get_withdrawals(db: Db) -> WithdrawalsOut:
    """Newest first."""
    return await summary.list_withdrawals(db)
