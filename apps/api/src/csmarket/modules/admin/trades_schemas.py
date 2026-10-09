"""Wire shapes for ``/api/v1/admin/trades`` — the admin «Обмены» table: every order is a
row (a trade), whatever its source (Waxpeer, Skinslink, LIS-SKINS) and channel.

Soʻm are whole digits; USD are decimal strings with six places. The buyer's trade link never
leaves whole (``trade_link_masked``), and no Steam id appears.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from csmarket.modules.admin.orders_schemas import AttentionReason, FailureReason
from csmarket.modules.orders.api import OrderStatusOut, TradeRowState

#: The table's tabs: ``active`` = on its way (``buying`` / ``sent``), ``hold`` = accepted
#: under Steam's protection, ``attention`` = an open attention of any source, ``refunds`` =
#: the money went back.
TradesView = Literal["all", "active", "hold", "attention", "refunds"]


class AdminTradeItem(BaseModel):
    """The skin bought."""

    #: The market name (English, as in Steam).
    name: str
    phase: str | None
    #: The catalogue image on our image host.
    image_url: str | None
    #: The catalogue's rarity colour (``#rrggbb``).
    rarity_color: str | None
    #: The bought offer's float, trailing zeros dropped; ``null`` on older orders.
    float_value: str | None


class AdminTradeBuyer(BaseModel):
    """Who placed the order."""

    id: str
    display_name: str | None
    avatar_url: str | None


class AdminTradeRow(BaseModel):
    """One line of the «Обмены» table."""

    number: str
    created_at: datetime
    status: OrderStatusOut
    source: Literal["waxpeer", "skinslink", "lisskins"]
    channel: Literal["site", "api"]
    #: The API key owner's name for an ``api`` order; ``null`` for the site.
    api_owner: str | None
    item: AdminTradeItem
    #: Whole soʻm, digits (what the buyer saw).
    price_uzs: str
    #: The order's price, USD.
    price_usd: str
    #: What the market charged (else the cost agreed at checkout), USD.
    cost_usd: str
    #: ``price_usd`` − ``cost_usd``.
    margin_usd: str
    #: ``margin_usd`` / ``price_usd`` × 100, one decimal; ``null`` for a zero price.
    margin_pct: str | None
    #: ``wallet``, ``usd_wallet``, a kassa or ``mock``; ``null`` until paid.
    paid_with: str | None
    buyer: AdminTradeBuyer
    #: Steam's trade offer id, whichever market sent it; ``null`` until known.
    steam_offer_id: str | None
    offer_url: str | None
    #: ``…?partner=<id>&token=••••<last 2>``.
    trade_link_masked: str | None
    #: The trade in one vocabulary for every source (``orders.trade_row``).
    trade_state: TradeRowState
    #: When Steam's protection of the accepted trade ends; ``null`` when none runs.
    protected_until: datetime | None
    #: Why the order failed or was refunded.
    failure_reason: FailureReason | None
    #: The open attention of the trade or purchase, any source.
    attention_reason: AttentionReason | None
    #: The source's own status: Waxpeer's code as digits, Skinslink's or LIS-SKINS' word.
    source_status: str | None


class AdminTradeCounts(BaseModel):
    """The tab badges (they ignore ``q``)."""

    all: int
    active: int
    hold: int
    attention: int
    refunds: int


class AdminTradesOut(BaseModel):
    """A page of the table, the tab counts, and the cursor for the next page."""

    items: list[AdminTradeRow]
    counts: AdminTradeCounts
    next_cursor: str | None


__all__ = [
    "AdminTradeBuyer",
    "AdminTradeCounts",
    "AdminTradeItem",
    "AdminTradeRow",
    "AdminTradesOut",
    "TradesView",
]
