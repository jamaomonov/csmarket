# apps/api/src/csmarket/modules/sales/views.py
"""Sales as their seller sees them: one by number, and the shape of the answer.

A page of sales loads its items, cards and requests in one query each (no N+1).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import and_, func, not_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.cursor import decode_cursor, encode_cursor
from csmarket.core.money import wire_uzs
from csmarket.core.numbers import is_sale_number
from csmarket.modules.sales.models import PayoutCard, PayoutRequest, Sale, SaleItem
from csmarket.modules.sales.schemas import (
    OFFER_URL,
    SaleCardOut,
    SaleItemOut,
    SaleOfferOut,
    SaleOut,
)


@dataclass(frozen=True)
class SaleRow:
    """A sale and what its page shows of its items, card and request."""

    sale: Sale
    items: list[SaleItem]
    card: PayoutCard | None
    request: PayoutRequest | None


async def rows_of(db: AsyncSession, sales: list[Sale]) -> list[SaleRow]:
    """``sales`` with their items, cards and requests: three queries for any number."""
    if not sales:
        return []
    ids = [s.id for s in sales]
    items: dict[str, list[SaleItem]] = defaultdict(list)
    for item in await db.scalars(
        select(SaleItem).where(SaleItem.sale_id.in_(ids)).order_by(SaleItem.price_uzs.desc())
    ):
        items[item.sale_id].append(item)
    card_ids = {s.payout_card_id for s in sales if s.payout_card_id is not None}
    cards = {
        c.id: c
        for c in (
            await db.scalars(select(PayoutCard).where(PayoutCard.id.in_(card_ids)))
            if card_ids
            else []
        )
    }
    requests = {
        r.sale_id: r
        for r in await db.scalars(select(PayoutRequest).where(PayoutRequest.sale_id.in_(ids)))
    }
    return [
        SaleRow(
            sale=s,
            items=items[s.id],
            card=cards.get(s.payout_card_id) if s.payout_card_id else None,
            request=requests.get(s.id),
        )
        for s in sales
    ]


def sale_out(row: SaleRow) -> SaleOut:
    """The seller's view of ``row``."""
    s = row.sale
    offer = None
    if s.status == "offered" and s.trade_offer_id:
        offer = SaleOfferOut(
            url=OFFER_URL.format(id=s.trade_offer_id),
            bot_name=s.bot_name,
            expires_at=s.offer_expiry_at,
        )
    to_card = s.payout_to == "card"
    zero = Decimal(0)
    return SaleOut(
        number=s.number,
        status=s.status,  # type: ignore[arg-type]  # the column's check admits only these
        payout_to=s.payout_to,  # type: ignore[arg-type]
        card=SaleCardOut(type=row.card.type, last4=row.card.last4)  # type: ignore[arg-type]
        if row.card is not None
        else None,
        items_uzs=wire_uzs(s.items_uzs),
        bonus_uzs=wire_uzs(zero if to_card else s.payout_uzs - s.items_uzs),
        fee_uzs=wire_uzs(s.items_uzs - s.payout_uzs if to_card else zero),
        payout_uzs=wire_uzs(s.payout_uzs),
        items=[
            SaleItemOut(
                asset_id=i.asset_id,
                name=i.name,
                image_url=i.image_url,
                price_uzs=wire_uzs(i.price_uzs),
            )
            for i in row.items
        ],
        offer=offer,
        money_at=s.hold_end_at if s.status == "hold" else None,
        payout_status=row.request.status if row.request is not None else None,  # type: ignore[arg-type]
        created_at=s.created_at,
    )


async def owned_sale(db: AsyncSession, user_id: str, number: str) -> SaleRow | None:
    """``user_id``'s sale ``number``; ``None`` for anyone else's, unknown or malformed."""
    if not is_sale_number(number):
        return None
    sale = await db.scalar(
        select(Sale)
        .where(Sale.number == number, Sale.user_id == user_id)
        .execution_options(populate_existing=True)
    )
    if sale is None:
        return None
    [row] = await rows_of(db, [sale])
    return row


#: Sales per page of «Продажи».
PAGE_SIZE = 20


async def list_sales(
    db: AsyncSession, user_id: str, cursor: str | None, *, limit: int = PAGE_SIZE
) -> tuple[list[SaleRow], str | None]:
    """One newest-first page of ``user_id``'s sales and the cursor of the next page.

    A sale Skinslink refused at once (``closed`` with no deposit) is left out: the seller saw
    the refusal on the spot.

    Raises:
        ValidationError: ``cursor`` is not one this API issued (``code="cursor"``).
    """
    stmt = (
        select(Sale)
        .where(
            Sale.user_id == user_id, not_(and_(Sale.status == "closed", Sale.trade_id.is_(None)))
        )
        .order_by(Sale.created_at.desc(), Sale.id.desc())
        .limit(limit + 1)
    )
    if cursor is not None:
        stamp, sale_id = decode_cursor(cursor)
        stmt = stmt.where(
            or_(Sale.created_at < stamp, and_(Sale.created_at == stamp, Sale.id < sale_id))
        )
    found = list((await db.scalars(stmt)).all())
    page = found[:limit]
    more = len(found) > limit
    next_cursor = encode_cursor(page[-1].created_at, page[-1].id) if more else None
    return await rows_of(db, page), next_cursor


async def pending_uzs(db: AsyncSession, user_id: str) -> Decimal:
    """«Ожидает зачисления»: the payouts of ``user_id``'s balance sales still in ``hold``."""
    total = await db.scalar(
        select(func.coalesce(func.sum(Sale.payout_uzs), 0)).where(
            Sale.user_id == user_id, Sale.status == "hold", Sale.payout_to == "balance"
        )
    )
    return Decimal(total or 0)


__all__ = ["PAGE_SIZE", "SaleRow", "list_sales", "owned_sale", "pending_uzs", "rows_of", "sale_out"]
