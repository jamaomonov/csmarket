"""One row per counted order of a window: revenue, real cost, profit, in soʻm and USD.

A counted order is paid in the window and not refunded; ``earned`` = delivered. Cost is
``orders.api.spent_usd_sql`` (the market's charge, else the agreed cost); soʻm at the order's
own CBU snapshot (``fx_snapshots.usd_uzs``), rounded to whole soʻm, never today's rate.
"""

from __future__ import annotations

from sqlalchemy import Date, Subquery, cast, func, select

from csmarket.modules.analytics.window import Channel, Window
from csmarket.modules.fx.api import FxSnapshot
from csmarket.modules.lisskins.api import LisskinsPurchase
from csmarket.modules.orders.api import Order, SkinTrade, spent_usd_sql
from csmarket.modules.skins.api import SkinItem
from csmarket.modules.skinslink.api import SkinslinkPurchase


def order_lines(w: Window, channel: Channel) -> Subquery:
    """The window's counted orders (see the module docstring)."""
    cost_usd = spent_usd_sql()
    cost_uzs = func.round(cost_usd * FxSnapshot.usd_uzs)
    stmt = (
        select(
            Order.id.label("order_id"),
            Order.number.label("number"),
            Order.user_id.label("user_id"),
            cast(func.timezone("Asia/Tashkent", Order.paid_at), Date).label("day"),
            Order.paid_at.label("paid_at"),
            (Order.status == "delivered").label("earned"),
            Order.source.label("source"),
            Order.channel.label("channel"),
            Order.api_key_id.label("api_key_id"),
            Order.paid_with.label("paid_with"),
            Order.skin_item_id.label("skin_item_id"),
            Order.market_hash_name.label("name"),
            SkinItem.category.label("category"),
            SkinItem.image_url.label("image_url"),
            Order.price_uzs.label("revenue_uzs"),
            Order.price_usd.label("revenue_usd"),
            cost_usd.label("cost_usd"),
            cost_uzs.label("cost_uzs"),
            (Order.price_uzs - cost_uzs).label("profit_uzs"),
            (Order.price_usd - cost_usd).label("profit_usd"),
        )
        .select_from(Order)
        .join(FxSnapshot, FxSnapshot.id == Order.fx_snapshot_id)
        .outerjoin(SkinItem, SkinItem.id == Order.skin_item_id)
        .outerjoin(SkinTrade, SkinTrade.order_id == Order.id)
        .outerjoin(SkinslinkPurchase, SkinslinkPurchase.order_id == Order.id)
        .outerjoin(LisskinsPurchase, LisskinsPurchase.order_id == Order.id)
        .where(Order.paid_at >= w.start, Order.paid_at < w.end, Order.refunded_at.is_(None))
    )
    if channel != "all":
        stmt = stmt.where(Order.channel == channel)
    return stmt.subquery("lines")


__all__ = ["order_lines"]
