"""The admin «Обмены» table: every order as a trade, whatever its source and channel.

Reads only. A page is one statement (the trade, the purchases, the buyer, the catalogue item
and an API order's key owner are joins); the tab counts are one more, over every order.
The row's state comes from ``orders.trade_row``, whose SQL twins filter the tabs.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from csmarket.core.clock import now
from csmarket.core.config import get_settings
from csmarket.core.money import wire_uzs
from csmarket.modules.admin.order_query import (
    AnySelect,
    after,
    fetch_page,
    joined_purchase,
    matching,
    spent,
    usd,
    with_sources,
)
from csmarket.modules.admin.trades_schemas import AdminTradeCounts, AdminTradeRow, TradesView
from csmarket.modules.lisskins.api import LisskinsPurchase
from csmarket.modules.orders.api import (
    ACTIVE_SQL,
    OPEN_ATTENTION_SQL,
    Order,
    PurchaseRow,
    SkinTrade,
    in_protection_sql,
    open_attention,
    protection_end,
    row_state,
)
from csmarket.modules.public_api.api import ApiKey
from csmarket.modules.skins.api import SkinItem, steam_image
from csmarket.modules.skinslink.api import SkinslinkPurchase
from csmarket.modules.users.api import User, mask_trade_link

_Owner = aliased(User, name="api_owner")
_PCT = Decimal("0.1")


def _rows() -> AnySelect:
    """Orders with every source, the buyer, the item and the key owner, newest first."""
    stmt = (
        select(
            Order,
            SkinTrade,
            SkinslinkPurchase,
            LisskinsPurchase,
            User.display_name,
            User.avatar_url,
            SkinItem.image_url,
            SkinItem.rarity_color,
            _Owner.display_name,
        )
        .join(User, User.id == Order.user_id)
        .join(SkinItem, SkinItem.id == Order.skin_item_id)
        .outerjoin(ApiKey, ApiKey.id == Order.api_key_id)
        .outerjoin(_Owner, _Owner.id == ApiKey.user_id)
    )
    return with_sources(stmt)


def _view(stmt: AnySelect, view: TradesView, at: datetime) -> AnySelect:
    match view:
        case "active":
            return stmt.where(ACTIVE_SQL)
        case "hold":
            return stmt.where(in_protection_sql(at))
        case "attention":
            return stmt.where(OPEN_ATTENTION_SQL)
        case "refunds":
            return stmt.where(Order.refunded_at.is_not(None))
        case "all":
            return stmt


def _offer_id(trade: SkinTrade | None, bought: PurchaseRow | None) -> str | None:
    if isinstance(bought, LisskinsPurchase):
        return bought.steam_trade_offer_id
    if isinstance(bought, SkinslinkPurchase):
        return bought.offer_id
    return None if trade is None else trade.trade_id


def _source_status(trade: SkinTrade | None, bought: PurchaseRow | None) -> str | None:
    if bought is not None:
        return bought.status
    if trade is None or trade.status is None:
        return None
    return str(trade.status)


def _masked(order: Order) -> str | None:
    # An erased link is stored masked already (and would not parse again).
    if order.trade_link_erased_at is not None:
        return order.trade_link
    return mask_trade_link(order.trade_link)


# Any: one row of :func:`_rows`.
def _row(found: Any, at: datetime, image_host: str) -> AdminTradeRow:
    order, trade, sl, ls, name, avatar, image, rarity, owner = found
    bought = joined_purchase(sl, ls)
    margin = order.price_usd - spent(order, trade, bought)
    offer = _offer_id(trade, bought)
    pct = (margin / order.price_usd * 100).quantize(_PCT) if order.price_usd else None
    return AdminTradeRow.model_validate(
        {
            "number": order.number,
            "created_at": order.created_at,
            "status": order.status,
            "source": order.source,
            "channel": order.channel,
            "api_owner": owner if order.channel == "api" else None,
            "item": {
                "name": order.market_hash_name,
                "phase": order.phase or None,
                "image_url": steam_image(image, host=image_host),
                "rarity_color": rarity,
                "float_value": None
                if order.float_value is None
                else format(order.float_value.normalize(), "f"),
            },
            "price_uzs": wire_uzs(order.price_uzs),
            "price_usd": usd(order.price_usd),
            "cost_usd": usd(order.price_usd - margin),
            "margin_usd": usd(margin),
            "margin_pct": None if pct is None else f"{pct:f}",
            "paid_with": order.paid_with,
            "buyer": {"id": order.user_id, "display_name": name, "avatar_url": avatar},
            "steam_offer_id": offer,
            "offer_url": f"https://steamcommunity.com/tradeoffer/{offer}/" if offer else None,
            "trade_link_masked": _masked(order),
            "trade_state": row_state(order, trade, bought, at),
            "protected_until": protection_end(order, trade, bought),
            "failure_reason": order.failure_reason,
            "attention_reason": open_attention(trade, bought),
            "source_status": _source_status(trade, bought),
        }
    )


async def _counts(db: AsyncSession, at: datetime) -> AdminTradeCounts:
    stmt = with_sources(
        select(
            func.count(),
            func.count().filter(ACTIVE_SQL),
            func.count().filter(in_protection_sql(at)),
            func.count().filter(OPEN_ATTENTION_SQL),
            func.count().filter(Order.refunded_at.is_not(None)),
        ).select_from(Order)
    ).order_by(None)
    found = (await db.execute(stmt)).one()
    return AdminTradeCounts(
        all=int(found[0]),
        active=int(found[1]),
        hold=int(found[2]),
        attention=int(found[3]),
        refunds=int(found[4]),
    )


async def list_trades(
    db: AsyncSession, *, view: TradesView, q: str | None, cursor: str | None, limit: int
) -> tuple[list[AdminTradeRow], AdminTradeCounts, str | None]:
    """Every order newest first (keyset on ``(created_at DESC, id DESC)``), narrowed by the
    tab and ``q`` (a number prefix, part of the name, or a Steam offer id); the counts ignore
    ``q``. Two statements whatever the page size."""
    at = now()
    stmt = after(matching(_view(_rows(), view, at), q), cursor)
    page, next_cursor = await fetch_page(db, stmt, limit)
    host = get_settings().skins_image_host
    return [_row(found, at, host) for found in page], await _counts(db, at), next_cursor


__all__ = ["list_trades"]
