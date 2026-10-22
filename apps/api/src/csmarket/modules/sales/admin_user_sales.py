"""The user page's «Продажи» (admin): what the user sold us, with the skins of each sale.

Two queries for the page whatever its size (the sales, then their items) and one for the
totals.
"""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.money import wire_uzs
from csmarket.modules.sales.admin_sales import sale_row, user_of, users_by_id
from csmarket.modules.sales.admin_schemas import (
    AdminSaleSkinOut,
    AdminUserSaleOut,
    AdminUserSalesOut,
)
from csmarket.modules.sales.models import Sale, SaleItem

#: Sales on the user page.
USER_SALES = 20
#: A sale whose skins reached us: in Steam's hold or past it.
SOLD = ("hold", "credited", "payout", "closed")


async def user_sales(db: AsyncSession, user_id: str) -> AdminUserSalesOut:
    """The user's latest :data:`USER_SALES` sales with their skins, and what they sold in all."""
    sales = list(
        (
            await db.scalars(
                select(Sale)
                .where(Sale.user_id == user_id)
                .order_by(Sale.created_at.desc(), Sale.id.desc())
                .limit(USER_SALES)
            )
        ).all()
    )
    skins: defaultdict[str, list[AdminSaleSkinOut]] = defaultdict(list)
    if sales:
        rows = await db.execute(
            select(SaleItem.sale_id, SaleItem.name, SaleItem.image_url)
            .where(SaleItem.sale_id.in_([s.id for s in sales]))
            .order_by(SaleItem.price_uzs.desc(), SaleItem.asset_id)
        )
        for sale_id, name, image in rows.all():
            skins[sale_id].append(AdminSaleSkinOut(name=name, image_url=image))
    count, total = (
        await db.execute(
            select(func.count(), func.coalesce(func.sum(Sale.payout_uzs), 0)).where(
                Sale.user_id == user_id, Sale.status.in_(SOLD)
            )
        )
    ).one()
    user = user_of(await users_by_id(db, [user_id]), user_id)
    return AdminUserSalesOut(
        sold_count=int(count),
        sold_uzs=wire_uzs(Decimal(total)),
        items=[
            AdminUserSaleOut(
                **sale_row(s, user).model_dump(exclude={"first_item", "items_count"}),
                items=skins[s.id],
                first_item=skins[s.id][0] if skins[s.id] else None,
                items_count=len(skins[s.id]),
            )
            for s in sales
        ],
    )


__all__ = ["USER_SALES", "user_sales"]
