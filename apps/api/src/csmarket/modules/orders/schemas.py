"""Request and response shapes of the customer's order routes."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from csmarket.modules.orders.trade_view import RefundedTo, SkinTradeOut

OrderStatusOut = Literal[
    "pending", "paid", "buying", "trade_sent", "delivered", "cancelled", "failed", "returned"
]


class OrderCreateIn(BaseModel):
    """Buy one skin: the offer the buyer chose and the price the panel showed them."""

    model_config = ConfigDict(extra="forbid")

    slug: Annotated[str, Field(min_length=1, max_length=160)]
    #: The offer picked on the item page.
    listing_id: Annotated[int, Field(strict=True, gt=0)]
    #: Whole soʻm the panel showed; a JSON integer only.
    price_uzs: Annotated[int, Field(strict=True, gt=0)]


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


class OrdersPage(BaseModel):
    """A page of the customer's orders, newest first."""

    items: list[OrderOut]
    next_cursor: str | None


__all__ = ["OrderCreateIn", "OrderOut", "OrderStatusOut", "OrdersPage"]
