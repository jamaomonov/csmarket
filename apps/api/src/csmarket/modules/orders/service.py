"""Order reads for their owner: one by number, the newest-first list, and the response shape.

A ``pending`` order past ``expires_at`` is shown as ``cancelled`` (and not payable) at
once — the expiry sweep writes the status a moment later. The list hides cancelled orders
and those expired ones. One query per page reads the orders, their item images and their
trades together (no N+1).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Select, and_, not_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.clock import now
from csmarket.core.config import get_settings
from csmarket.core.cursor import decode_cursor, encode_cursor
from csmarket.core.numbers import is_number, is_topup_number
from csmarket.modules.lisskins.api import LisskinsPurchase
from csmarket.modules.orders.models import Order, SkinTrade
from csmarket.modules.orders.schemas import OrderOut, OrderStatusOut
from csmarket.modules.orders.trade_view import skin_trade_out
from csmarket.modules.skins.api import SkinItem, steam_image
from csmarket.modules.skinslink.api import SkinslinkPurchase

#: Orders per page of ``GET /me/orders``.
PAGE_SIZE = 20


@dataclass(frozen=True)
class OrderRow:
    """An order with what its response needs: the trade and the item image."""

    order: Order
    trade: SkinTrade | None
    #: The item's image, already on our image host.
    image_url: str | None
    #: A Skinslink order's purchase.
    purchase: SkinslinkPurchase | LisskinsPurchase | None = None
    #: The catalogue item's exterior code and rarity colour.
    exterior: str | None = None
    rarity_color: str | None = None

    def out(self) -> OrderOut:
        """The owner's view of this row."""
        return order_out(
            self.order,
            self.trade,
            self.image_url,
            self.purchase,
            exterior=self.exterior,
            rarity_color=self.rarity_color,
        )


def is_expired(order: Order, at: datetime | None = None) -> bool:
    """A ``pending`` order whose time to pay has run out."""
    return order.status == "pending" and order.expires_at <= (at or now())


def effective_status(order: Order, at: datetime | None = None) -> OrderStatusOut:
    """The status the buyer sees: an expired ``pending`` order reads ``cancelled``."""
    status: OrderStatusOut = order.status  # type: ignore[assignment] # ck_orders_status
    return "cancelled" if is_expired(order, at) else status


def order_out(
    order: Order,
    trade: SkinTrade | None,
    image_url: str | None,
    purchase: SkinslinkPurchase | LisskinsPurchase | None = None,
    *,
    exterior: str | None = None,
    rarity_color: str | None = None,
) -> OrderOut:
    """The owner's view of ``order``.

    Args:
        order: The order row.
        trade: Its ``skin_trades`` row, if the worker has created one.
        image_url: The item's image on our image host.
        purchase: A Skinslink order's purchase row.
        exterior: The catalogue item's exterior code.
        rarity_color: The catalogue item's rarity colour.
    """
    at = now()
    status = effective_status(order, at)
    return OrderOut(
        number=order.number,
        status=status,
        slug=order.slug,
        name=order.market_hash_name,
        phase=order.phase or None,
        image_url=image_url,
        float_value=_plain(order.float_value),
        paint_seed=order.paint_seed,
        exterior=exterior,
        rarity_color=rarity_color,
        price_uzs=str(order.price_uzs),
        price_usd=str(order.price_usd),
        created_at=order.created_at,
        expires_at=order.expires_at,
        paid_at=order.paid_at,
        delivered_at=order.delivered_at,
        paid_with=order.paid_with,
        refunded_to="balance" if order.refunded_to == "balance" else None,
        payable=status == "pending",
        trade=skin_trade_out(order, trade, purchase=purchase),
    )


def _plain(value: Decimal | None) -> str | None:
    """``0.621400`` → ``"0.6214"``; ``None`` stays."""
    if value is None:
        return None
    text = format(value.normalize(), "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


_Row = tuple[
    Order,
    SkinTrade | None,
    str | None,
    SkinslinkPurchase | None,
    LisskinsPurchase | None,
    str | None,
    str | None,
]


def _rows() -> Select[
    Order, SkinTrade, str | None, SkinslinkPurchase, LisskinsPurchase, str | None, str | None
]:
    # Outer joins: each of the three is ``None`` on a row without one.
    return (
        select(
            Order,
            SkinTrade,
            SkinItem.image_url,
            SkinslinkPurchase,
            LisskinsPurchase,
            SkinItem.exterior,
            SkinItem.rarity_color,
        )
        .join(SkinItem, SkinItem.id == Order.skin_item_id)
        .outerjoin(SkinTrade, SkinTrade.order_id == Order.id)
        .outerjoin(SkinslinkPurchase, SkinslinkPurchase.order_id == Order.id)
        .outerjoin(LisskinsPurchase, LisskinsPurchase.order_id == Order.id)
    )


def _row(found: _Row) -> OrderRow:
    order, trade, image, sl, ls, exterior, rarity_color = found
    return OrderRow(
        order=order,
        trade=trade,
        image_url=steam_image(image, host=get_settings().skins_image_host),
        purchase=sl or ls,
        exterior=exterior,
        rarity_color=rarity_color,
    )


async def get_owned(db: AsyncSession, user_id: str, number: str) -> OrderRow | None:
    """``user_id``'s order ``number``; ``None`` for anyone else's, unknown or malformed."""
    if not is_number(number) or is_topup_number(number):
        return None
    found = (
        await db.execute(_rows().where(Order.number == number, Order.user_id == user_id))
    ).one_or_none()
    if found is None:
        return None
    return _row(found)


async def list_for_user(
    db: AsyncSession, user_id: str, cursor: str | None, *, limit: int = PAGE_SIZE
) -> tuple[list[OrderRow], str | None]:
    """One newest-first page of ``user_id``'s orders and the cursor of the next page.

    Cancelled orders and unpaid ones past their time are left out.

    Raises:
        ValidationError: ``cursor`` is not one this API issued (``code="cursor"``).
    """
    stmt = (
        _rows()
        .where(
            Order.user_id == user_id,
            Order.status != "cancelled",
            not_(and_(Order.status == "pending", Order.expires_at <= now())),
        )
        .order_by(Order.created_at.desc(), Order.id.desc())
        .limit(limit + 1)
    )
    if cursor is not None:
        stamp, order_id = decode_cursor(cursor)
        stmt = stmt.where(
            or_(
                Order.created_at < stamp,
                and_(Order.created_at == stamp, Order.id < order_id),
            )
        )
    found = [_row(row) for row in (await db.execute(stmt)).all()]
    page = found[:limit]
    more = len(found) > limit
    next_cursor = encode_cursor(page[-1].order.created_at, page[-1].order.id) if more else None
    return page, next_cursor


__all__ = [
    "PAGE_SIZE",
    "OrderRow",
    "effective_status",
    "get_owned",
    "is_expired",
    "list_for_user",
    "order_out",
]
