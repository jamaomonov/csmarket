"""Pydantic shapes of the site's API-key routes."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from csmarket.modules.public_api.ip_allowlist import MAX_ENTRIES


class ApiKeyOut(BaseModel):
    """The live key's public facts (never the token)."""

    model_config = ConfigDict(frozen=True)

    id: str
    pricing_profile: str
    created_at: datetime
    last_used_at: datetime | None
    ip_allowlist: list[str]


class IpAllowlistIn(BaseModel):
    """The key's new IP allow-list; ``[]`` lets any address in."""

    model_config = ConfigDict(extra="forbid")

    ip_allowlist: list[str] = Field(max_length=MAX_ENTRIES + 1)


class ApiKeyIssuedOut(BaseModel):
    """A freshly issued key: the token is shown this once."""

    model_config = ConfigDict(frozen=True)

    id: str
    token: str
    pricing_profile: str
    created_at: datetime


class CatalogItemOut(BaseModel):
    """One catalogue item priced for the caller's tariff (USD, three decimals)."""

    model_config = ConfigDict(frozen=True)

    item_id: str
    slug: str
    market_hash_name: str
    exterior: str | None
    price_usd: str
    #: Only on the ``cost`` tariff; the key is omitted otherwise.
    retail_price_usd: str | None = None
    stock: int
    updated_at: datetime | None


class CatalogPageOut(BaseModel):
    """A page of the catalogue feed."""

    model_config = ConfigDict(frozen=True)

    items: list[CatalogItemOut]
    next_cursor: str | None


class OfferOut(BaseModel):
    """One purchasable offer; ``offer_id`` is opaque and bound to its item."""

    model_config = ConfigDict(frozen=True, populate_by_name=True)

    offer_id: str
    float_value: float | None = Field(alias="float")
    paint_seed: int | None
    # Any: sticker objects as the storefront shows them (name, image, slot, wear).
    stickers: list[dict[str, Any]]
    price_usd: str
    #: Only on the ``cost`` tariff; the key is omitted otherwise.
    retail_price_usd: str | None = None
    delivery: Literal["instant"]


class OfferCheckOut(BaseModel):
    """Whether an offer is still for sale, and at what price — ask right before you charge."""

    model_config = ConfigDict(frozen=True)

    offer_id: str
    status: Literal["available", "gone", "unconfirmed"] = Field(
        description="available: for sale at price_usd. gone: sold; pick another offer. "
        "unconfirmed: the market did not answer; price_usd is the last known price and the "
        "order checks again."
    )
    #: ``null`` when ``gone``.
    price_usd: str | None
    #: Only on the ``cost`` tariff, and not when ``gone``.
    retail_price_usd: str | None = None


#: An API order's status as the partner reads it (spec §5; no new FSM states).
PublicOrderStatus = Literal["buying", "trade_sent", "delivered", "refunded"]
#: Why an API order's money came back (spec §5, a closed list).
PublicRefundReason = Literal[
    "sold_out",
    "invalid_trade_link",
    "trade_hold",
    "price_moved",
    "supplier_refused",
    "cancelled_by_support",
]


class ApiOrderIn(BaseModel):
    """Buy one skin: an offer of the item (or its cheapest under the cap) for a trade link."""

    model_config = ConfigDict(extra="forbid")

    item_id: Annotated[str, Field(min_length=1, max_length=64)]
    #: An opaque id from ``/catalog/{item_id}/offers``; omitted buys the cheapest offer.
    offer_id: Annotated[str | None, Field(max_length=512)] = None
    #: The most the caller pays, USD with up to three decimals.
    max_price_usd: Annotated[str, Field(pattern=r"^\d{1,6}(\.\d{1,3})?$")]
    trade_link: Annotated[str, Field(min_length=1, max_length=512)]
    #: The caller's own id, unique per account (any of its keys); a repeat answers 409
    #: ``duplicate_client_order_id``.
    client_order_id: Annotated[
        str, Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.:-]+$")
    ]


class TradeLinkCheckIn(BaseModel):
    """A buyer's Steam trade link to check."""

    model_config = ConfigDict(extra="forbid")

    trade_link: Annotated[str, Field(min_length=1, max_length=512)]


class TradeLinkCheckOut(BaseModel):
    """``unavailable`` means the check could not run: do not block a purchase on it."""

    model_config = ConfigDict(frozen=True)

    verdict: Literal["ok", "bad", "unavailable"] = Field(
        description="ok: the link can receive a trade. bad: it cannot, see reason. "
        "unavailable: the check could not run; do not block a purchase on it."
    )
    reason: (
        Literal["invalid_link", "private_inventory", "trade_ban", "hold", "not_found"] | None
    ) = Field(description="Why the link is bad; null for ok and unavailable.")


class PublicOrderItemOut(BaseModel):
    """The catalogue item an order bought."""

    model_config = ConfigDict(frozen=True)

    item_id: str
    slug: str
    market_hash_name: str


class PublicTradeOut(BaseModel):
    """The Steam trade of an order whose offer is out; a time is ``None`` until known."""

    model_config = ConfigDict(frozen=True)

    offer_sent_at: datetime | None
    accepted_at: datetime | None
    #: When Steam's trade protection ends.
    release_at: datetime | None
    #: Steam's trade offer id: ``https://steamcommunity.com/tradeoffer/{id}/``.
    steam_offer_id: str | None = Field(
        default=None,
        description="Steam's trade offer id; the buyer accepts it at "
        "https://steamcommunity.com/tradeoffer/{id}/",
    )
    #: The sender's Steam name when the market gives it; usually ``null``.
    seller_name: str | None = Field(
        default=None,
        description="The sender's Steam name when the market gives it; usually null.",
    )


class PublicRefundOut(BaseModel):
    """The money returned to the USD wallet."""

    model_config = ConfigDict(frozen=True)

    amount_usd: str
    reason: PublicRefundReason


class PublicOrderOut(BaseModel):
    """An API order as its owner sees it — never the source market or its ids."""

    model_config = ConfigDict(frozen=True)

    #: Our order number.
    order_id: str
    client_order_id: str
    status: PublicOrderStatus
    item: PublicOrderItemOut
    price_usd: str
    created_at: datetime
    trade: PublicTradeOut | None
    refund: PublicRefundOut | None


class PublicOrdersPage(BaseModel):
    """A page of the account's API orders, newest first."""

    model_config = ConfigDict(frozen=True)

    items: list[PublicOrderOut]
    next_cursor: str | None


class MeKeyOut(BaseModel):
    """The calling key."""

    model_config = ConfigDict(frozen=True)

    id: str
    pricing_profile: str
    created_at: datetime


class MeLimitsOut(BaseModel):
    """Requests allowed per minute and key."""

    model_config = ConfigDict(frozen=True)

    read_per_min: int
    orders_per_min: int
    feed_per_min: int
    check_per_min: int = Field(
        description="Trade-link checks (POST /tradelink/check) allowed per minute."
    )


class MeOut(BaseModel):
    """The caller's balance, wallet switch, key and limits."""

    model_config = ConfigDict(frozen=True)

    balance_usd: str
    usd_wallet_enabled: bool
    key: MeKeyOut
    limits: MeLimitsOut


class WebhookIn(BaseModel):
    """``PUT /public/webhook`` body."""

    model_config = ConfigDict(frozen=True)

    url: str = Field(max_length=500, description="`https` URL; its host must be public.")


class WebhookDeliveryOut(BaseModel):
    """The latest delivery attempt state of the partner's webhook."""

    model_config = ConfigDict(frozen=True)

    event: str
    status: str
    attempts: int
    last_status_code: int | None
    at: datetime


class WebhookOut(BaseModel):
    """The partner's webhook and how its last delivery went."""

    model_config = ConfigDict(frozen=True)

    url: str
    created_at: datetime
    last_delivery: WebhookDeliveryOut | None


__all__ = [
    "ApiKeyIssuedOut",
    "ApiKeyOut",
    "ApiOrderIn",
    "CatalogItemOut",
    "CatalogPageOut",
    "MeKeyOut",
    "MeLimitsOut",
    "MeOut",
    "OfferOut",
    "PublicOrderItemOut",
    "PublicOrderOut",
    "PublicOrderStatus",
    "PublicOrdersPage",
    "PublicRefundOut",
    "PublicRefundReason",
    "PublicTradeOut",
    "WebhookDeliveryOut",
    "WebhookIn",
    "WebhookOut",
]
