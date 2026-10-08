"""Wire shapes for ``/api/v1/admin/orders`` and ``/api/v1/admin/trades`` (the admin SPA's
orders and trades pages).

Soʻm are whole digits (``core.money.wire_uzs``); USD are decimal strings with six places;
Waxpeer units are integers (1000 = $1). The buyer's trade link never leaves whole:
``trade_link_masked`` keeps ``partner`` and the token's last 2 characters.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, StringConstraints

from csmarket.modules.orders.api import OrderStatusOut, SkinTradeState

#: ``skin_trades.attention_reason`` (``orders.models.ATTENTION_REASONS``; a unit test pins it).
AttentionReason = Literal[
    "buy_unconfirmed", "ambiguous_trade", "rolled_back", "source_forbidden", "audit_divergence"
]
#: ``orders.failure_reason`` (``orders.models.FAILURE_REASONS``; a unit test pins it).
FailureReason = Literal[
    "sold_out",
    "source_low_balance",
    "invalid_trade_link",
    "not_accepted",
    "admin",
    "trade_hold",
    "price_moved",
]
#: The trades page's tabs.
TradesView = Literal["all", "active", "attention"]
#: What the operator found, trimmed; an empty note is stored as ``null``.
Note = Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)]


class AdminOrderUser(BaseModel):
    """Who placed the order."""

    id: str
    display_name: str | None


class AdminOrderRow(BaseModel):
    """One line of the orders list (also the user card's orders)."""

    number: str
    status: OrderStatusOut
    #: The skin's market name (English, as in Steam).
    name: str
    phase: str | None
    #: Whole soʻm, digits.
    price_uzs: str
    #: ``wallet``, ``click``, ``payme``, ``uzum`` or ``mock``; ``null`` until paid.
    paid_with: str | None
    user: AdminOrderUser
    created_at: datetime
    #: The trade's **open** attention (unresolved); ``null`` when none waits for an admin.
    attention_reason: AttentionReason | None


class AdminOrdersOut(BaseModel):
    """A page of orders, newest first, and the cursor for the next (``null`` on the last)."""

    items: list[AdminOrderRow]
    next_cursor: str | None


class AdminTradeSummary(BaseModel):
    """The trade behind a row of the trades page."""

    #: Waxpeer's trade status code; ``null`` until the buy reached Waxpeer.
    status: int | None
    #: The state the buyer reads (``buying``, ``offer_sent``, ``accepted``, ``released``,
    #: ``failed``).
    state: SkinTradeState
    #: The trade's open attention, as on the order row.
    attention_reason: AttentionReason | None
    send_until: datetime | None


class AdminTradeRow(AdminOrderRow):
    """One line of the trades page: the order row and its trade."""

    trade: AdminTradeSummary


class AdminTradeCounts(BaseModel):
    """The tab badges (they ignore ``q``)."""

    #: Orders ``buying`` or ``trade_sent``.
    active: int
    #: Trades with an unresolved attention.
    attention: int


class AdminTradesOut(BaseModel):
    """A page of trades, the tab counts, and the cursor for the next page."""

    items: list[AdminTradeRow]
    counts: AdminTradeCounts
    next_cursor: str | None


class AdminOrderFull(BaseModel):
    """Every ``orders`` column (the trade link masked, the checkout's idempotency key left
    out) plus the money an operator weighs."""

    id: str
    number: str
    user_id: str
    status: OrderStatusOut
    skin_item_id: str
    market_hash_name: str
    phase: str | None
    slug: str
    #: Where the skin is bought (spec 2026-10-06).
    source: Literal["waxpeer", "skinslink", "lisskins"]
    #: The prefixed offer chosen at checkout (``wx:<id>`` / ``sl:<id>``).
    offer_id: str | None
    #: The Waxpeer listing behind it; ``None`` for a Skinslink order.
    listing_id: int | None
    #: Units agreed at checkout (the worker's price cap).
    cost_units: int
    cost_usd: str
    price_usd: str
    price_uzs: str
    fx_snapshot_id: str
    #: The USD → UZS rate of that snapshot (the CBU's).
    fx_rate: str
    #: Percent added to it for the soʻm price (ADR-0011).
    fx_uplift_pct: str
    #: ``price_usd`` − what Waxpeer charged (``bought_units`` / 1000), else − ``cost_usd``.
    margin_usd: str
    #: The bought offer's float (trailing zeros dropped) and pattern; ``None`` on older orders.
    float_value: str | None
    paint_seed: int | None
    #: ``site`` or ``api``; for ``api`` the key, the client's own id and the tariff.
    channel: str
    api_key_id: str | None
    client_order_id: str | None
    pricing_profile: str | None
    #: ``…?partner=<id>&token=••••<last 2>``.
    trade_link_masked: str | None
    paid_with: str | None
    created_at: datetime
    updated_at: datetime
    expires_at: datetime
    paid_at: datetime | None
    delivered_at: datetime | None
    cancelled_at: datetime | None
    failed_at: datetime | None
    refunded_at: datetime | None
    refunded_to: Literal["balance"] | None
    failure_reason: FailureReason | None
    claimed_at: datetime | None
    #: ``hostname:pid`` of the worker that took it.
    claimed_by: str | None
    #: When the sweeps look at it next (a buy attempt's lease while one runs).
    next_check_at: datetime | None


class AdminTradeOut(BaseModel):
    """The order's ``skin_trades`` row as the operator needs it."""

    #: Our id at Waxpeer (= the order id) — what their dashboard is searched by.
    project_id: str
    waxpeer_id: int | None
    listing_id: int
    paid_units: int
    bought_units: int | None
    #: Waxpeer's trade status code; ``null`` until the buy reached Waxpeer.
    status: int | None
    escrow_status: str | None
    #: Steam's trade offer id.
    trade_id: str | None
    offer_url: str | None
    send_until: datetime | None
    release_date: datetime | None
    accepted_at: datetime | None
    is_released: bool
    reason: str | None
    # Any: Waxpeer's penalties object as received (never PII).
    penalties: Any
    # Any: the seller's public name, avatar, level and since, as stored (scalars).
    seller: dict[str, Any]
    buy_pending: bool
    buy_unconfirmed_at: datetime | None
    #: Set whether resolved or not; ``resolved_at`` says which.
    attention_reason: AttentionReason | None
    audit_verdict: str | None
    last_polled_at: datetime | None
    resolved_at: datetime | None
    #: The admin's user id.
    resolved_by: str | None
    resolved_note: str | None


class AdminOrderPaymentOut(BaseModel):
    """One payment attempt of the order (open it at ``/admin/payments/{id}``)."""

    id: str
    provider: str
    status: Literal["created", "pending", "succeeded", "failed", "cancelled", "refunded"]
    amount_uzs: str
    created_at: datetime


class AdminSkinslinkPurchaseOut(BaseModel):
    """A Skinslink order's purchase as the operator needs it (spec 2026-10-06 §7)."""

    #: Our idempotency key at Skinslink — what their dashboard is searched by.
    merchant_tx_id: str
    #: The Skinslink item (Steam asset) bought.
    asset_id: str
    purchase_id: int | None
    #: Skinslink's status word (``new`` … ``reverted``).
    status: str | None
    #: Steam's trade offer id.
    offer_id: str | None
    offer_url: str | None
    fail_reason: str | None
    #: What Skinslink charged, USD with six places.
    amount_usd: str | None
    hold_end_date: datetime | None
    buy_pending: bool
    buy_unconfirmed_at: datetime | None
    attention_reason: AttentionReason | None
    resolved_at: datetime | None


class AdminLisskinsPurchaseOut(BaseModel):
    """A LIS-SKINS order's purchase as the operator needs it (spec 2026-10-07 §7)."""

    #: Our idempotency key at LIS-SKINS — what its purchase history is searched by.
    custom_id: str
    #: The LIS-SKINS lot bought.
    skin_id: int
    purchase_id: int | None
    #: The skin's status word (``processing`` … ``return``).
    status: str | None
    return_reason: str | None
    error: str | None
    #: Steam's trade offer id.
    offer_id: str | None
    offer_url: str | None
    offer_expiry_at: datetime | None
    #: What LIS-SKINS charged, USD with six places.
    amount_usd: str | None
    buy_pending: bool
    buy_unconfirmed_at: datetime | None
    attention_reason: AttentionReason | None
    resolved_at: datetime | None


class AdminOrderDetail(BaseModel):
    """The order page: the order, its buyer, its trade, its payments and what may be done."""

    order: AdminOrderFull
    user: AdminOrderUser
    trade: AdminTradeOut | None
    #: A Skinslink order's purchase; ``None`` for a Waxpeer order.
    skinslink: AdminSkinslinkPurchaseOut | None = None
    #: A LIS-SKINS order's purchase; ``None`` otherwise.
    lisskins: AdminLisskinsPurchaseOut | None = None
    #: Oldest first.
    payments: list[AdminOrderPaymentOut]
    #: «Вернуть деньги на баланс» would succeed now.
    can_refund: bool
    #: «Повторить покупку» would succeed now.
    can_retry: bool


class AdminResolveIn(BaseModel):
    """«Разобрано»: what the operator found, optional."""

    model_config = ConfigDict(extra="forbid")

    note: Note | None = None


__all__ = [
    "AdminLisskinsPurchaseOut",
    "AdminOrderDetail",
    "AdminOrderFull",
    "AdminOrderPaymentOut",
    "AdminOrderRow",
    "AdminOrderUser",
    "AdminOrdersOut",
    "AdminResolveIn",
    "AdminSkinslinkPurchaseOut",
    "AdminTradeCounts",
    "AdminTradeOut",
    "AdminTradeRow",
    "AdminTradeSummary",
    "AdminTradesOut",
    "AttentionReason",
    "FailureReason",
    "TradesView",
]
