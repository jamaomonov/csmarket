"""What the admin orders list and the «Обмены» table share: the search, the keyset cursor,
a page fetch and the money an operator weighs.

Every statement here selects ``Order`` first and outer-joins the order's ``skin_trades``,
``skinslink_purchases`` and ``lisskins_purchases`` (one row each at most: their key is the
order id), so a page is one statement whatever its sources.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy import Select, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.cursor import decode_cursor, encode_cursor
from csmarket.modules.lisskins.api import LisskinsPurchase
from csmarket.modules.orders.api import Order, PurchaseRow, SkinTrade
from csmarket.modules.skinslink.api import SkinslinkPurchase

#: The longest ``q`` still tried as a number prefix (an order number is 8 characters).
_NUMBER_LENGTH = 8
_USD = Decimal("0.000001")

# Any: a statement selecting ``Order`` first and whatever else its page needs.
type AnySelect = Select[*tuple[Any, ...]]


def _like_escape(needle: str) -> str:
    return needle.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def with_sources[*Ts](stmt: Select[*Ts]) -> Select[*Ts]:
    """``stmt`` outer-joined to the order's trade and purchases, newest first (keyset-ready)."""
    return (
        stmt.outerjoin(SkinTrade, SkinTrade.order_id == Order.id)
        .outerjoin(SkinslinkPurchase, SkinslinkPurchase.order_id == Order.id)
        .outerjoin(LisskinsPurchase, LisskinsPurchase.order_id == Order.id)
        .order_by(Order.created_at.desc(), Order.id.desc())
    )


def matching[*Ts](stmt: Select[*Ts], q: str | None) -> Select[*Ts]:
    """``q`` = a number prefix (upper-cased, ≤ 8 characters), part of the item's name, or a
    Steam trade offer id (exact, any source); ``%`` and ``_`` are literal."""
    needle = (q or "").strip()
    if not needle:
        return stmt
    found = [
        Order.market_hash_name.ilike(f"%{_like_escape(needle)}%", escape="\\"),
        SkinTrade.trade_id == needle,
        SkinslinkPurchase.offer_id == needle,
        LisskinsPurchase.steam_trade_offer_id == needle,
    ]
    if len(needle) <= _NUMBER_LENGTH:
        found.append(Order.number.like(f"{_like_escape(needle.upper())}%", escape="\\"))
    return stmt.where(or_(*found))


def after[*Ts](stmt: Select[*Ts], cursor: str | None) -> Select[*Ts]:
    """The rows after ``cursor`` on ``(created_at DESC, id DESC)``."""
    if cursor is None:
        return stmt
    stamp, last_id = decode_cursor(cursor)
    return stmt.where(
        or_(Order.created_at < stamp, and_(Order.created_at == stamp, Order.id < last_id))
    )


# Any: a row of whatever the statement selects; its first column is the ``Order``.
async def fetch_page(db: AsyncSession, stmt: AnySelect, limit: int) -> tuple[list[Any], str | None]:
    """Up to ``limit`` rows and the cursor of the next page (``None`` on the last)."""
    rows = list((await db.execute(stmt.limit(limit + 1))).all())
    page, more = rows[:limit], len(rows) > limit
    last: Order | None = page[-1][0] if more else None
    return page, (encode_cursor(last.created_at, last.id) if last is not None else None)


def joined_purchase(
    sl: SkinslinkPurchase | None, ls: LisskinsPurchase | None
) -> PurchaseRow | None:
    """The order's Skinslink or LIS-SKINS purchase off an outer-joined row."""
    return sl if sl is not None else ls


def usd(value: Decimal) -> str:
    """USD with six places."""
    return f"{value.quantize(_USD):f}"


def spent(order: Order, trade: SkinTrade | None, bought: PurchaseRow | None) -> Decimal:
    """What the market charged, USD; the agreed cost until it says."""
    if trade is not None and trade.bought_units is not None:
        return Decimal(trade.bought_units) / 1000
    if bought is not None and bought.amount_units is not None:
        return Decimal(bought.amount_units) / 1000
    return order.cost_usd


__all__ = [
    "AnySelect",
    "after",
    "fetch_page",
    "joined_purchase",
    "matching",
    "spent",
    "usd",
    "with_sources",
]
