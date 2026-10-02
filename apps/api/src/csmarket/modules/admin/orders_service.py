"""Admin orders and trades: search, the trades page with its attention queue, one order's
page (spec §13, rulings R3, K).

Reads only; the writes are ``orders``' own (``orders.api``: ``resolve_attention``,
``admin_refund``, ``retry_buy``) — the route audits them. A list page is one statement
whatever its size (the buyer's name and the trade are joins); the trades page adds one for
the tab counts; an order's page is a fixed four.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import Select, and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from csmarket.core.cursor import decode_cursor, encode_cursor
from csmarket.core.errors import NotFoundError
from csmarket.core.money import wire_uzs
from csmarket.core.numbers import is_number, is_topup_number
from csmarket.modules.admin.orders_schemas import (
    AdminOrderDetail,
    AdminOrderFull,
    AdminOrderPaymentOut,
    AdminOrderRow,
    AdminOrderUser,
    AdminTradeCounts,
    AdminTradeOut,
    AdminTradeRow,
    AdminTradeSummary,
    TradesView,
)
from csmarket.modules.fx.api import FxSnapshot
from csmarket.modules.orders.api import (
    Order,
    SkinTrade,
    can_refund,
    can_retry,
    trade_state,
)
from csmarket.modules.payments.api import Payment
from csmarket.modules.users.api import User, mask_trade_link

#: Orders with their trade (``None`` on an outer join) and the buyer's name.
type _Rows = Select[Order, SkinTrade, str | None]
#: Orders on a user's card.
CARD_ORDERS = 20
#: The longest ``q`` still tried as a number prefix (an order number is 8 characters).
_NUMBER_LENGTH = 8
#: Order statuses whose skin is on its way (the trades page's ``active`` tab).
_ACTIVE = ("buying", "trade_sent")
_USD = Decimal("0.000001")


def _like_escape(needle: str) -> str:
    return needle.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _open_attention() -> ColumnElement[bool]:
    """An attention waiting for an admin: set and not resolved."""
    return and_(SkinTrade.attention_reason.is_not(None), SkinTrade.resolved_at.is_(None))


def _matching(stmt: _Rows, q: str | None) -> _Rows:
    """``q`` = a number prefix (upper-cased, ≤ 8 characters) or part of the item's name;
    ``%`` and ``_`` are literal."""
    needle = (q or "").strip()
    if not needle:
        return stmt
    by_name = Order.market_hash_name.ilike(f"%{_like_escape(needle)}%", escape="\\")
    if len(needle) > _NUMBER_LENGTH:
        return stmt.where(by_name)
    by_number = Order.number.like(f"{_like_escape(needle.upper())}%", escape="\\")
    return stmt.where(or_(by_number, by_name))


def _rows(*, trades_only: bool = False) -> _Rows:
    """Orders with their trade and buyer's name, newest first (keyset-ready)."""
    stmt = select(Order, SkinTrade, User.display_name).join(User, User.id == Order.user_id)
    stmt = (
        stmt.join(SkinTrade, SkinTrade.order_id == Order.id)
        if trades_only
        else stmt.outerjoin(SkinTrade, SkinTrade.order_id == Order.id)
    )
    return stmt.order_by(Order.created_at.desc(), Order.id.desc())


def _after(stmt: _Rows, cursor: str | None) -> _Rows:
    if cursor is None:
        return stmt
    stamp, last_id = decode_cursor(cursor)
    return stmt.where(
        or_(Order.created_at < stamp, and_(Order.created_at == stamp, Order.id < last_id))
    )


def _open_reason(trade: SkinTrade | None) -> str | None:
    if trade is None or trade.resolved_at is not None:
        return None
    return trade.attention_reason


def order_row(order: Order, trade: SkinTrade | None, display_name: str | None) -> AdminOrderRow:
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
            "attention_reason": _open_reason(trade),
        }
    )


async def _page(
    db: AsyncSession, stmt: _Rows, limit: int
) -> tuple[list[tuple[Order, SkinTrade | None, str | None]], str | None]:
    # An outer join: the trade is ``None`` on an order without one.
    rows: list[tuple[Order, SkinTrade | None, str | None]] = [
        (o, t, n) for o, t, n in (await db.execute(stmt.limit(limit + 1))).all()
    ]
    page, more = rows[:limit], len(rows) > limit
    last = page[-1][0] if more else None
    return page, (encode_cursor(last.created_at, last.id) if last is not None else None)


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
    stmt = _after(_matching(_rows(), q), cursor)
    if status is not None:
        stmt = stmt.where(Order.status == status)
    if user_id is not None:
        stmt = stmt.where(Order.user_id == user_id)
    page, next_cursor = await _page(db, stmt, limit)
    return [order_row(o, t, n) for o, t, n in page], next_cursor


async def recent_orders(db: AsyncSession, user_id: str) -> list[AdminOrderRow]:
    """The user's latest :data:`CARD_ORDERS` orders (the admin user card)."""
    page, _ = await _page(db, _rows().where(Order.user_id == user_id), CARD_ORDERS)
    return [order_row(o, t, n) for o, t, n in page]


async def _counts(db: AsyncSession) -> AdminTradeCounts:
    found = (
        await db.execute(
            select(
                func.count().filter(Order.status.in_(_ACTIVE)),
                func.count().filter(_open_attention()),
            )
            .select_from(Order)
            .join(SkinTrade, SkinTrade.order_id == Order.id)
        )
    ).one()
    return AdminTradeCounts(active=int(found[0]), attention=int(found[1]))


async def list_trades(
    db: AsyncSession, *, view: TradesView, q: str | None, cursor: str | None, limit: int
) -> tuple[list[AdminTradeRow], AdminTradeCounts, str | None]:
    """Orders with a trade, newest first: ``all``, ``active`` (``buying`` / ``trade_sent``)
    or ``attention`` (an unresolved attention). The counts ignore ``q``."""
    stmt = _after(_matching(_rows(trades_only=True), q), cursor)
    if view == "active":
        stmt = stmt.where(Order.status.in_(_ACTIVE))
    elif view == "attention":
        stmt = stmt.where(_open_attention())
    page, next_cursor = await _page(db, stmt, limit)
    items = [
        AdminTradeRow.model_validate(
            {
                **order_row(o, t, n).model_dump(),
                "trade": AdminTradeSummary.model_validate(
                    {
                        "status": t.status if t is not None else None,
                        "state": trade_state(o, t),
                        "attention_reason": _open_reason(t),
                        "send_until": t.send_until if t is not None else None,
                    }
                ),
            }
        )
        for o, t, n in page
    ]
    return items, await _counts(db), next_cursor


def _usd(value: Decimal) -> str:
    return f"{value.quantize(_USD):f}"


def _order_full(order: Order, trade: SkinTrade | None, fx_rate: Decimal) -> AdminOrderFull:
    spent = (
        Decimal(trade.bought_units) / 1000
        if trade is not None and trade.bought_units is not None
        else order.cost_usd
    )
    columns = {c.key: getattr(order, c.key) for c in Order.__table__.columns}
    del columns["trade_link"], columns["idempotency_key"], columns["trade_link_erased_at"]
    return AdminOrderFull.model_validate(
        {
            **columns,
            "phase": order.phase or None,
            "cost_usd": _usd(order.cost_usd),
            "price_usd": _usd(order.price_usd),
            "price_uzs": wire_uzs(order.price_uzs),
            "fx_rate": f"{fx_rate:f}",
            "margin_usd": _usd(order.price_usd - spent),
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
    payments = await db.scalars(
        select(Payment).where(Payment.order_id == order.id).order_by(Payment.created_at, Payment.id)
    )
    return AdminOrderDetail(
        order=_order_full(order, trade, Decimal(fx_rate)),
        user=AdminOrderUser(id=order.user_id, display_name=display_name),
        trade=_trade_out(trade) if trade is not None else None,
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
        can_refund=can_refund(order, trade),
        can_retry=can_retry(order, trade),
    )


__all__ = [
    "CARD_ORDERS",
    "list_orders",
    "list_trades",
    "order_detail",
    "order_row",
    "recent_orders",
]
