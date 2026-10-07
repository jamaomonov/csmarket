"""Request and response shapes of the customer's order routes."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator

from csmarket.modules.orders.trade_view import RefundedTo, SkinTradeOut
from csmarket.modules.skins.api import offer_id_of, parse_offer_id

OrderStatusOut = Literal[
    "pending", "paid", "buying", "trade_sent", "delivered", "cancelled", "failed", "returned"
]


class OrderCreateIn(BaseModel):
    """Buy one skin: the offer the buyer chose and the price the panel showed them."""

    model_config = ConfigDict(extra="forbid")

    slug: Annotated[str, Field(min_length=1, max_length=160)]
    #: The offer picked on the item page: ``wx:<id>`` / ``sl:<id>``; a bare integer reads as
    #: Waxpeer's (one release). Normalised to the prefixed string.
    listing_id: StrictInt | Annotated[str, Field(strict=True, max_length=310)]
    #: Whole soʻm the panel showed; a JSON integer only.
    price_uzs: Annotated[int, Field(strict=True, gt=0)]

    @field_validator("listing_id")
    @classmethod
    def _offer_id(cls, v: int | str) -> str:
        """``wx:…`` / ``sl:…`` whatever form the panel sent."""
        try:
            source, raw = parse_offer_id(v)
        except ValueError as exc:
            raise ValueError("not an offer id") from exc
        return offer_id_of(source, raw)


class OrderOut(BaseModel):
    """An order as its owner sees it."""

    number: str
    #: A ``pending`` order past ``expires_at`` reads ``cancelled`` before the sweep writes it.
    status: OrderStatusOut
    slug: str
    #: The skin's market name (English, as in Steam).
    name: str
    phase: str | None
    image_url: str | None
    #: Whole soʻm as digits.
    price_uzs: str
    price_usd: str
    created_at: datetime
    expires_at: datetime
    paid_at: datetime | None
    delivered_at: datetime | None
    #: ``wallet``, ``click``, ``payme``, ``uzum`` or ``mock``; ``None`` until paid.
    paid_with: str | None
    #: Where a refund went; ``None`` when there was none.
    refunded_to: RefundedTo | None
    #: The order can be paid now (``pending`` and not expired).
    payable: bool
    trade: SkinTradeOut | None


#: How an order can be paid: the balance (ruling R8) or a kassa (``mock`` outside prod).
PayProvider = Literal["wallet", "click", "payme", "uzum", "mock"]
#: The language of the kassa's page and of the order page the buyer returns to.
PayLocale = Literal["ru", "uz", "en"]


class OrderPayIn(BaseModel):
    """Pay an order from the balance or through a kassa."""

    model_config = ConfigDict(extra="forbid")

    provider: PayProvider
    locale: PayLocale


class OrderPayOut(BaseModel):
    """The order after the pay call, and where to pay when a kassa takes the money."""

    order: OrderOut
    #: The kassa's payment page; ``None`` for the balance (the order is already ``paid``).
    intent_url: str | None


class OrdersPage(BaseModel):
    """A page of the customer's orders, newest first."""

    items: list[OrderOut]
    next_cursor: str | None


__all__ = [
    "OrderCreateIn",
    "OrderOut",
    "OrderPayIn",
    "OrderPayOut",
    "OrderStatusOut",
    "OrdersPage",
    "PayLocale",
    "PayProvider",
]
