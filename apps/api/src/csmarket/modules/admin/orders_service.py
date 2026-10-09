"""Admin orders: search, the user and API-key cards' rows, one order's page (spec §13,
rulings R3, K). The «Обмены» table is ``trades_service``.

Reads only; the writes are ``orders``' own (``orders.api``: ``resolve_attention``,
``admin_refund``, ``retry_buy``) — the route audits them. A list page is one statement
whatever its size (the buyer's name, the trade and the purchases are joins); an order's page
is a fixed four.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.errors import NotFoundError
from csmarket.core.money import wire_uzs
from csmarket.core.numbers import is_number, is_topup_number
from csmarket.modules.admin.order_query import (
    after,
    fetch_page,
    joined_purchase,
    matching,
    spent,
    usd,
    with_sources,
)
from csmarket.modules.admin.orders_schemas import (
    AdminLisskinsPurchaseOut,
    AdminOrderDetail,
    AdminOrderFull,
    AdminOrderPaymentOut,
    AdminOrderRow,
    AdminOrderUser,
    AdminSkinslinkPurchaseOut,
    AdminTradeOut,
)
from csmarket.modules.fx.api import FxSnapshot
from csmarket.modules.lisskins.api import LisskinsPurchase
from csmarket.modules.orders.api import (
    Order,
    PurchaseRow,
    SkinTrade,
    can_refund,
    can_retry,
    open_attention,
    protection_end,
    protection_is_estimate,
    purchase_of,
)
from csmarket.modules.payments.api import Payment
from csmarket.modules.skinslink.api import SkinslinkPurchase
from csmarket.modules.users.api import User, mask_trade_link

#: Orders with their trade, purchases (``None`` on the outer joins) and the buyer's name.
type _Rows = Select[Order, SkinTrade, SkinslinkPurchase, LisskinsPurchase, str | None]
#: Orders on a user's card.
CARD_ORDERS = 20


def _rows() -> _Rows:
    """Orders with their trade, purchases and buyer's name, newest first (keyset-ready)."""
    return with_sources(
        select(Order, SkinTrade, SkinslinkPurchase, LisskinsPurchase, User.display_name).join(
            User, User.id == Order.user_id
        )
    )


def order_row(
    order: Order,
    trade: SkinTrade | None,
    bought: PurchaseRow | None,
    display_name: str | None,
) -> AdminOrderRow:
    """One list line."""
    return AdminOrderRow.model_validate(
        {
            "number": order.number,
            "status": order.status,
            "name": order.market_hash_name,
            "phase": order.phase or None,
            "price_uzs": wire_uzs(order.price_uzs),
            "paid_with": order.paid_with,
            "user": AdminOrderUser(id=order.user_id, display_name=display_name),
            "created_at": order.created_at,
            "attention_reason": open_attention(trade, bought),
            "protected_until": protection_end(order, trade, bought),
            "protected_estimated": protection_is_estimate(bought),
        }
    )


# Any: the rows of :func:`_rows` (an outer join leaves the trade and purchases ``None``).
def _row_list(page: list[Any]) -> list[AdminOrderRow]:
    return [order_row(o, t, joined_purchase(sl, ls), n) for o, t, sl, ls, n in page]


async def list_orders(
    db: AsyncSession,
    *,
    q: str | None,
    status: str | None,
    user_id: str | None,
    cursor: str | None,
    limit: int,
) -> tuple[list[AdminOrderRow], str | None]:
    """Orders newest first, keyset on ``(created_at DESC, id DESC)``; filters combine with
    AND. One statement whatever the page size."""
    stmt = after(matching(_rows(), q), cursor)
    if status is not None:
        stmt = stmt.where(Order.status == status)
    if user_id is not None:
        stmt = stmt.where(Order.user_id == user_id)
    page, next_cursor = await fetch_page(db, stmt, limit)
    return _row_list(page), next_cursor


async def recent_orders(db: AsyncSession, user_id: str) -> list[AdminOrderRow]:
    """The user's latest :data:`CARD_ORDERS` orders (the admin user card)."""
    page, _ = await fetch_page(db, _rows().where(Order.user_id == user_id), CARD_ORDERS)
    return _row_list(page)


async def recent_key_orders(db: AsyncSession, api_key_id: str) -> list[AdminOrderRow]:
    """The latest :data:`CARD_ORDERS` orders placed through one API key."""
    page, _ = await fetch_page(db, _rows().where(Order.api_key_id == api_key_id), CARD_ORDERS)
    return _row_list(page)


def _order_full(
    order: Order, trade: SkinTrade | None, purchase: PurchaseRow | None, fx_rate: Decimal
) -> AdminOrderFull:
    charged = spent(order, trade, purchase)
    columns = {c.key: getattr(order, c.key) for c in Order.__table__.columns}
    del columns["trade_link"], columns["idempotency_key"], columns["trade_link_erased_at"]
    return AdminOrderFull.model_validate(
        {
            **columns,
            "phase": order.phase or None,
            "cost_usd": usd(order.cost_usd),
            "price_usd": usd(order.price_usd),
            "price_uzs": wire_uzs(order.price_uzs),
            "fx_rate": f"{fx_rate:f}",
            "fx_uplift_pct": f"{order.fx_uplift_pct:f}",
            "float_value": None
            if order.float_value is None
            else format(order.float_value.normalize(), "f"),
            "margin_usd": usd(order.price_usd - charged),
            "protected_until": protection_end(order, trade, purchase),
            "protected_estimated": protection_is_estimate(purchase),
            # An erased link is stored masked already (and would not parse again).
            "trade_link_masked": order.trade_link
            if order.trade_link_erased_at is not None
            else mask_trade_link(order.trade_link),
        }
    )


def _trade_out(trade: SkinTrade) -> AdminTradeOut:
    fields = {
        name: getattr(trade, name) for name in AdminTradeOut.model_fields if name != "offer_url"
    }
    offer = f"https://steamcommunity.com/tradeoffer/{trade.trade_id}/" if trade.trade_id else None
    return AdminTradeOut.model_validate({**fields, "offer_url": offer})


def _purchase_out(p: SkinslinkPurchase) -> AdminSkinslinkPurchaseOut:
    offer = f"https://steamcommunity.com/tradeoffer/{p.offer_id}/" if p.offer_id else None
    amount = None if p.amount_units is None else usd(Decimal(p.amount_units) / 1000)
    fields = {
        name: getattr(p, name)
        for name in AdminSkinslinkPurchaseOut.model_fields
        if name not in ("offer_url", "amount_usd")
    }
    return AdminSkinslinkPurchaseOut.model_validate(
        {**fields, "offer_url": offer, "amount_usd": amount}
    )


def _lisskins_out(p: LisskinsPurchase) -> AdminLisskinsPurchaseOut:
    offer = p.steam_trade_offer_id
    return AdminLisskinsPurchaseOut.model_validate(
        {
            "custom_id": p.custom_id,
            "skin_id": p.skin_id,
            "purchase_id": p.purchase_id,
            "status": p.status,
            "return_reason": p.return_reason,
            "error": p.error,
            "offer_id": offer,
            "offer_url": f"https://steamcommunity.com/tradeoffer/{offer}/" if offer else None,
            "offer_expiry_at": p.offer_expiry_at,
            "amount_usd": None if p.amount_units is None else usd(Decimal(p.amount_units) / 1000),
            "buy_pending": p.buy_pending,
            "buy_unconfirmed_at": p.buy_unconfirmed_at,
            "attention_reason": p.attention_reason,
            "resolved_at": p.resolved_at,
        }
    )


async def order_detail(db: AsyncSession, number: str) -> AdminOrderDetail:
    """Order ``number``'s page: the order, its buyer, its trade, payments, the actions allowed.

    Raises:
        NotFoundError: malformed, a top-up's, or unknown.
    """
    if not is_number(number) or is_topup_number(number):
        raise NotFoundError("order not found")
    found = (
        await db.execute(
            select(Order, User.display_name, FxSnapshot.usd_uzs)
            .join(User, User.id == Order.user_id)
            .join(FxSnapshot, FxSnapshot.id == Order.fx_snapshot_id)
            .where(Order.number == number)
        )
    ).one_or_none()
    if found is None:
        raise NotFoundError("order not found")
    order, display_name, fx_rate = found
    trade = await db.scalar(select(SkinTrade).where(SkinTrade.order_id == order.id))
    purchase = await purchase_of(db, order, lock=False)
    payments = await db.scalars(
        select(Payment).where(Payment.order_id == order.id).order_by(Payment.created_at, Payment.id)
    )
    return AdminOrderDetail(
        order=_order_full(order, trade, purchase, Decimal(fx_rate)),
        user=AdminOrderUser(id=order.user_id, display_name=display_name),
        trade=_trade_out(trade) if trade is not None else None,
        skinslink=_purchase_out(purchase) if isinstance(purchase, SkinslinkPurchase) else None,
        lisskins=_lisskins_out(purchase) if isinstance(purchase, LisskinsPurchase) else None,
        payments=[
            AdminOrderPaymentOut.model_validate(
                {
                    "id": p.id,
                    "provider": p.provider,
                    "status": p.status,
                    "amount_uzs": wire_uzs(p.amount_uzs),
                    "created_at": p.created_at,
                }
            )
            for p in payments
        ],
        can_refund=can_refund(order, trade, purchase=purchase),
        can_retry=can_retry(order, trade),
    )


__all__ = [
    "CARD_ORDERS",
    "list_orders",
    "order_detail",
    "order_row",
    "recent_orders",
]
