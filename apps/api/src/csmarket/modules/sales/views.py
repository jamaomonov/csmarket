# apps/api/src/csmarket/modules/sales/views.py
"""Sales as their seller sees them: one by number, and the shape of the answer.

A page of sales loads its items, cards and requests in one query each (no N+1).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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


__all__ = ["SaleRow", "owned_sale", "rows_of", "sale_out"]
