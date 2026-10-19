"""One row per counted order of a window: revenue, real cost, profit, in soʻm and USD.

A counted order is paid in the window, not refunded, and delivered or on its way (``paid``,
``buying``, ``trade_sent``): a ``failed`` / ``returned`` order waits for its refund and is not
counted. ``earned`` = delivered. Revenue in soʻm is ``price_uzs``; an API order stores 0 there
(``orders.api_checkout`` R1) and is worth its ``price_usd`` at its own rate. Cost is
``orders.api.spent_usd_sql`` (the market's charge, else the agreed cost); soʻm at the order's
own CBU snapshot (``fx_snapshots.usd_uzs``), rounded to whole soʻm, never today's rate.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import ColumnElement, Date, Subquery, case, cast, func, select

from csmarket.modules.analytics.window import Channel, Window
from csmarket.modules.fx.api import FxSnapshot
from csmarket.modules.lisskins.api import LisskinsPurchase
from csmarket.modules.orders.api import Order, SkinTrade, spent_usd_sql
from csmarket.modules.skins.api import SkinItem
from csmarket.modules.skinslink.api import SkinslinkPurchase

#: Paid and not given up: delivered, or still on its way to the buyer.
COUNTED = ("paid", "buying", "trade_sent", "delivered")


def revenue_uzs_sql() -> ColumnElement[Decimal]:
    """An order's price in soʻm: an API order's dollars at its own rate (needs ``FxSnapshot``
    joined on ``orders.fx_snapshot_id``)."""
    return case(
        (Order.channel == "api", func.round(Order.price_usd * FxSnapshot.usd_uzs)),
        else_=Order.price_uzs,
    )


def order_lines(w: Window, channel: Channel) -> Subquery:
    """The window's counted orders (see the module docstring)."""
    cost_usd = spent_usd_sql()
    cost_uzs = func.round(cost_usd * FxSnapshot.usd_uzs)
    revenue_uzs = revenue_uzs_sql()
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
            revenue_uzs.label("revenue_uzs"),
            Order.price_usd.label("revenue_usd"),
            cost_usd.label("cost_usd"),
            cost_uzs.label("cost_uzs"),
            (revenue_uzs - cost_uzs).label("profit_uzs"),
            (Order.price_usd - cost_usd).label("profit_usd"),
        )
        .select_from(Order)
        .join(FxSnapshot, FxSnapshot.id == Order.fx_snapshot_id)
        .outerjoin(SkinItem, SkinItem.id == Order.skin_item_id)
        .outerjoin(SkinTrade, SkinTrade.order_id == Order.id)
        .outerjoin(SkinslinkPurchase, SkinslinkPurchase.order_id == Order.id)
        .outerjoin(LisskinsPurchase, LisskinsPurchase.order_id == Order.id)
        .where(
            Order.paid_at >= w.start,
            Order.paid_at < w.end,
            Order.refunded_at.is_(None),
            Order.status.in_(COUNTED),
        )
    )
    if channel != "all":
        stmt = stmt.where(Order.channel == channel)
    return stmt.subquery("lines")


__all__ = ["COUNTED", "order_lines", "revenue_uzs_sql"]
