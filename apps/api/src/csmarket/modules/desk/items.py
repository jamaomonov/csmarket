"""Items after a deal is made (spec 2026-10-31-desk-v2, stage 2): add, delete, undo.

Adding or deleting re-splits the price over the deal's items, so both are refused
(``price_locked``) once any item is resolved — the split is fixed from then on. Undo puts a
sold or written-off item back to ``open`` and deletes its ledger row; a settled deal opens
again.
"""

from __future__ import annotations

from sqlalchemy import Text, cast, delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.clock import now
from csmarket.core.errors import ConflictError, NotFoundError
from csmarket.modules.admin.api import record
from csmarket.modules.desk.deals import (
    SETTLED,
    fill_images,
    items_of,
    load_deal,
    new_items,
    recost,
    require_live,
)
from csmarket.modules.desk.models import RESOLVED, DeskDeal, DeskDeposit, DeskEntry, DeskItem
from csmarket.modules.desk.schemas import ItemsIn

#: What undo takes back: the owner's own hand-booked endings.
UNDOABLE = ("sold", "written_off")


async def _item(db: AsyncSession, item_id: str) -> DeskItem:
    """The item ``FOR UPDATE``.

    Raises:
        NotFoundError: ``item_not_found``.
    """
    item = await db.scalar(
        select(DeskItem).where(cast(DeskItem.id, Text) == item_id).with_for_update()
    )
    if item is None:
        raise NotFoundError("no such item", code="item_not_found")
    return item


def _unlocked(items: list[DeskItem]) -> None:
    """Raises: ConflictError ``price_locked`` once an item of the deal is resolved."""
    if any(i.state in RESOLVED for i in items):
        raise ConflictError(
            "the deal's skins are fixed once one is sold, credited or written off",
            code="price_locked",
        )


async def add_items(db: AsyncSession, deal_id: str, body: ItemsIn) -> DeskDeal:
    """More skins for a deal; the price is split again over all of them.

    Raises:
        NotFoundError: ``deal_not_found``.
        ConflictError: ``deal_busy`` — the deal is cancelled; ``price_locked``.
    """
    deal = await load_deal(db, deal_id, lock=True)
    require_live(deal)
    items = await items_of(db, deal.id)
    _unlocked(items)
    added = new_items(deal.id, body.items)
    await fill_images(db, added)
    recost(deal, [*items, *added])
    deal.updated_at = now()
    db.add_all(added)
    await db.flush()
    return deal


async def delete_item(db: AsyncSession, item_id: str) -> DeskDeal:
    """An ``open`` skin taken off its deal; the price is split again over the rest.

    Raises:
        NotFoundError: ``item_not_found``.
        ConflictError: ``item_not_open``, ``price_locked``, ``last_item``.
    """
    item = await _item(db, item_id)
    deal = await load_deal(db, item.deal_id, lock=True)
    if item.state != "open":
        raise ConflictError("the item is not open", code="item_not_open")
    items = await items_of(db, deal.id)
    _unlocked(items)
    rest = [i for i in items if i.id != item.id]
    if not rest:
        raise ConflictError("a deal keeps at least one skin", code="last_item")
    recost(deal, rest)
    deal.updated_at = now()
    await db.delete(item)
    await db.flush()
    return deal


async def undo(db: AsyncSession, item_id: str, *, actor_id: str) -> DeskDeal:
    """A sold or written-off item back to ``open``: its ledger row deleted, audited.

    A settled deal opens again — ``received`` if a trade of it was accepted, else ``paid``.

    Raises:
        NotFoundError: ``item_not_found``.
        ConflictError: ``item_not_undoable`` — not sold or written off.
    """
    item = await _item(db, item_id)
    deal = await load_deal(db, item.deal_id, lock=True)
    was = item.state
    if was not in UNDOABLE:
        raise ConflictError("only a sold or written-off item is undone", code="item_not_undoable")
    await db.execute(
        delete(DeskEntry).where(
            DeskEntry.item_id == item.id, DeskEntry.kind.in_(("sale", "write_off"))
        )
    )
    item.state = "open"
    item.resolved_at = None
    item.sold_where = item.sold_currency = None
    item.sold_amount = item.sold_rate = item.sold_usd = None
    if was == "written_off":
        item.note = None  # the write-off's reason
    if deal.status in SETTLED:
        accepted = await db.scalar(
            select(DeskDeposit.id).where(
                DeskDeposit.deal_id == deal.id, DeskDeposit.accepted_at.is_not(None)
            )
        )
        deal.status = "received" if accepted is not None else "paid"
    deal.updated_at = now()
    await record(
        db,
        actor_id=actor_id,
        action="desk.item.undo",
        target_type="desk_item",
        target_id=item.id,
        payload={"deal_id": deal.id, "was": was},
    )
    await db.flush()
    return deal


__all__ = ["UNDOABLE", "add_items", "delete_item", "undo"]
