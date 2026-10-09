"""An order as the public API shows it, and the owner's API-order reads (spec 2026-10-09 §5).

No new FSM states (ADR-0007): ``paid`` / ``buying`` read ``buying``; ``trade_sent`` reads
``trade_sent`` until the buyer accepts, then ``delivered`` (Steam's trade protection may still
run: ``release_at``); a refunded order reads ``refunded`` with the amount and a reason from a
closed list; a ``failed`` / ``returned`` order without a refund is held for support and reads
``buying`` until a person settles it. The source market and its ids never appear.

The list filter mirrors :func:`public_status` in SQL, so a page holds what its rows say.
"""

from __future__ import annotations

from typing import cast

from sqlalchemy import ColumnElement, Select, and_, false, func, not_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.cursor import decode_cursor, encode_cursor
from csmarket.core.money import wire_usd
from csmarket.core.numbers import is_number, is_topup_number
from csmarket.modules.lisskins.api import LisskinsPurchase
from csmarket.modules.orders.models import Order, SkinTrade
from csmarket.modules.orders.trade_view import lisskins_state, purchase_state, trade_state
from csmarket.modules.public_api.api import (
    PublicOrderItemOut,
    PublicOrderOut,
    PublicOrderStatus,
    PublicRefundOut,
    PublicRefundReason,
    PublicTradeOut,
)
from csmarket.modules.skinslink.api import SkinslinkPurchase

#: Orders per page of ``GET /public/orders``.
PAGE_SIZE = 50

#: ``orders.failure_reason`` → the refund reason the partner reads.
_REASONS: dict[str, PublicRefundReason] = {
    "sold_out": "sold_out",
    "invalid_trade_link": "invalid_trade_link",
    "trade_hold": "trade_hold",
    "price_moved": "price_moved",
    "source_low_balance": "supplier_refused",
    "not_accepted": "supplier_refused",
    "admin": "cancelled_by_support",
}
#: A refund with no machine reason was a person's decision.
_DEFAULT_REASON: PublicRefundReason = "cancelled_by_support"

Purchase = SkinslinkPurchase | LisskinsPurchase


def _offer_id(trade: SkinTrade | None, purchase: Purchase | None) -> str | None:
    """Steam's trade offer id, whichever market sent it; ``None`` until known."""
    if isinstance(purchase, LisskinsPurchase):
        raw = purchase.steam_trade_offer_id
    elif isinstance(purchase, SkinslinkPurchase):
        raw = purchase.offer_id
    else:
        raw = None if trade is None else trade.trade_id
    return str(raw) if raw else None


def _seller_name(trade: SkinTrade | None) -> str | None:
    """The sender's public Steam name (Waxpeer only); ``None`` otherwise."""
    name = (trade.seller or {}).get("name") if trade is not None else None
    return name if isinstance(name, str) and name else None


def _accepted(order: Order, trade: SkinTrade | None, purchase: Purchase | None) -> bool:
    """Whether the buyer accepted the offer (Steam's protection may still hold the skin)."""
    if isinstance(purchase, LisskinsPurchase):
        return lisskins_state(order, purchase) == "accepted"
    if purchase is not None:
        return purchase_state(order, purchase) == "accepted"
    return trade_state(order, trade) in ("accepted", "released")


def public_status(
    order: Order, trade: SkinTrade | None, purchase: Purchase | None
) -> PublicOrderStatus:
    """The partner's status of ``order`` (spec §5's table)."""
    if order.refunded_at is not None:
        return "refunded"
    if order.status == "delivered":
        return "delivered"
    if order.status == "trade_sent":
        return "delivered" if _accepted(order, trade, purchase) else "trade_sent"
    # ``paid`` / ``buying``, and ``failed`` / ``returned`` held for support (no refund yet).
    return "buying"


def _trade(order: Order, trade: SkinTrade | None, purchase: Purchase | None) -> PublicTradeOut:
    release_at = None
    if trade is not None:
        release_at = trade.release_date
    elif isinstance(purchase, SkinslinkPurchase):
        release_at = purchase.hold_end_date
    accepted_at = trade.accepted_at if trade is not None else None
    return PublicTradeOut(
        offer_sent_at=order.trade_sent_at,
        accepted_at=accepted_at or order.delivered_at,
        release_at=release_at,
        steam_offer_id=_offer_id(trade, purchase),
        seller_name=_seller_name(trade),
    )


def public_order(
    order: Order, trade: SkinTrade | None, purchase: Purchase | None
) -> PublicOrderOut:
    """``order`` as its owner sees it over the API.

    Args:
        order: An API order.
        trade: Its ``skin_trades`` row (a Waxpeer buy), if any.
        purchase: Its Skinslink or LIS-SKINS purchase, if any.
    """
    status = public_status(order, trade, purchase)
    refund = None
    if status == "refunded":
        refund = PublicRefundOut(
            amount_usd=wire_usd(order.price_usd * 1000),
            reason=_REASONS.get(order.failure_reason or "", _DEFAULT_REASON),
        )
    return PublicOrderOut(
        order_id=order.number,
        # ``ck_orders_channel_fields``: an API order always has one.
        client_order_id=order.client_order_id or "",
        status=status,
        item=PublicOrderItemOut(
            item_id=order.skin_item_id, slug=order.slug, market_hash_name=order.market_hash_name
        ),
        price_usd=wire_usd(order.price_usd * 1000),
        created_at=order.created_at,
        trade=_trade(order, trade, purchase) if status in ("trade_sent", "delivered") else None,
        refund=refund,
    )


_Row = tuple[Order, SkinTrade | None, SkinslinkPurchase | None, LisskinsPurchase | None]


def _rows() -> Select[Order, SkinTrade, SkinslinkPurchase, LisskinsPurchase]:
    # Outer joins: each of the three is ``None`` on a row without one.
    return (
        select(Order, SkinTrade, SkinslinkPurchase, LisskinsPurchase)
        .outerjoin(SkinTrade, SkinTrade.order_id == Order.id)
        .outerjoin(SkinslinkPurchase, SkinslinkPurchase.order_id == Order.id)
        .outerjoin(LisskinsPurchase, LisskinsPurchase.order_id == Order.id)
    )


def _out(found: _Row) -> PublicOrderOut:
    order, trade, sl, ls = found
    return public_order(order, trade, sl or ls)


#: :func:`_accepted` in SQL; ``COALESCE``: the outer joins' NULLs read "not accepted".
_ACCEPTED: ColumnElement[bool] = func.coalesce(
    or_(
        SkinslinkPurchase.status.in_(("hold", "completed")),
        LisskinsPurchase.status == "accepted",
        SkinTrade.status == 5,
        SkinTrade.is_released.is_(True),
        and_(SkinTrade.status == 4, SkinTrade.release_date.is_not(None)),
    ),
    false(),
)


def _status_filter(status: PublicOrderStatus) -> ColumnElement[bool]:
    """:func:`public_status` ``== status`` as a SQL condition."""
    open_ = Order.refunded_at.is_(None)
    match status:
        case "refunded":
            return Order.refunded_at.is_not(None)
        case "delivered":
            return and_(
                open_,
                or_(Order.status == "delivered", and_(Order.status == "trade_sent", _ACCEPTED)),
            )
        case "trade_sent":
            return and_(open_, Order.status == "trade_sent", not_(_ACCEPTED))
        case "buying":
            return and_(open_, Order.status.not_in(("delivered", "trade_sent")))


async def get_for_owner(db: AsyncSession, user_id: str, number: str) -> PublicOrderOut | None:
    """API order ``number`` of ``user_id`` (placed with any of their keys); ``None`` for another
    user's, a site order or an unknown number."""
    if not is_number(number) or is_topup_number(number):
        return None
    stmt = _rows().where(Order.number == number, Order.user_id == user_id, Order.channel == "api")
    found = (await db.execute(stmt)).one_or_none()
    return None if found is None else _out(cast(_Row, found))


async def list_for_owner(
    db: AsyncSession, user_id: str, cursor: str | None, status: PublicOrderStatus | None
) -> tuple[list[PublicOrderOut], str | None]:
    """One newest-first page of the owner's API orders (optionally of one status) + next cursor.

    Every key the user ever had: a reissue hides nothing. ``ix_orders_user_created`` serves it.

    Raises:
        ValidationError: ``cursor`` is not one this API issued (``code="cursor"``).
    """
    stmt = (
        _rows()
        .where(Order.user_id == user_id, Order.channel == "api")
        .order_by(Order.created_at.desc(), Order.id.desc())
        .limit(PAGE_SIZE + 1)
    )
    if status is not None:
        stmt = stmt.where(_status_filter(status))
    if cursor is not None:
        stamp, order_id = decode_cursor(cursor)
        stmt = stmt.where(
            or_(Order.created_at < stamp, and_(Order.created_at == stamp, Order.id < order_id))
        )
    found = [cast(_Row, row) for row in (await db.execute(stmt)).all()]
    page = found[:PAGE_SIZE]
    more = len(found) > PAGE_SIZE
    last = page[-1][0] if page else None
    next_cursor = encode_cursor(last.created_at, last.id) if more and last else None
    return [_out(row) for row in page], next_cursor


__all__ = ["PAGE_SIZE", "get_for_owner", "list_for_owner", "public_order", "public_status"]
