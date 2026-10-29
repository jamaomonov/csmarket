"""Request and response models of ``/api/v1/admin/desk`` (spec 2026-10-29-desk).

Money leaves as plain strings (``"733.333333"``, ``"1300000"``); the admin formats it.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, Field, model_validator

Currency = Literal["UZS", "USD"]
Method = Literal["direct", "guarantor"]
Destination = Literal["skinslink", "stock"]
DealStatus = Literal["agreed", "paid", "received", "closed", "cancelled", "reverted"]
Amount = Annotated[Decimal, Field(gt=0, max_digits=18, decimal_places=6)]
Rate = Annotated[Decimal, Field(gt=0, max_digits=12, decimal_places=4)]


class ItemIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    asset_id: str | None = Field(default=None, max_length=32)
    image_url: str | None = Field(default=None, max_length=1000)
    skinslink_usd: Annotated[Decimal, Field(ge=0, max_digits=18, decimal_places=6)] | None = None
    destination: Destination


class _Price(BaseModel):
    paid_amount: Amount | None = None
    paid_currency: Currency | None = None
    rate: Rate | None = None
    paid_at: datetime | None = None

    @model_validator(mode="after")
    def _pair(self) -> _Price:
        if (self.paid_amount is None) != (self.paid_currency is None):
            raise ValueError("paid_amount and paid_currency go together")
        return self


class DealIn(_Price):
    trader: str = Field(min_length=1, max_length=120)
    note: str | None = Field(default=None, max_length=4000)
    trade_link: str | None = Field(default=None, max_length=300)
    method: Method = "direct"
    items: list[ItemIn] = Field(min_length=1, max_length=200)


class DealPatch(_Price):
    trader: str | None = Field(default=None, min_length=1, max_length=120)
    note: str | None = Field(default=None, max_length=4000)
    trade_link: str | None = Field(default=None, max_length=300)
    method: Method | None = None
    status: DealStatus | None = None
    #: ``true`` stamps «Подтвердил гаранту», ``false`` clears it.
    guarantor_released: bool | None = None


class SellIn(BaseModel):
    where: str = Field(min_length=1, max_length=120)
    amount: Amount
    currency: Currency
    rate: Rate | None = None
    at: datetime | None = None


class MoveIn(BaseModel):
    destination: Destination


class WriteOffIn(BaseModel):
    note: str = Field(min_length=1, max_length=500)


class WithdrawalIn(BaseModel):
    amount_usd: Amount
    note: str | None = Field(default=None, max_length=500)


class InventoryIn(BaseModel):
    trade_link: str = Field(min_length=1, max_length=300)


class InventoryItemOut(BaseModel):
    asset_id: str
    name: str
    image_url: str | None
    price_usd: str


class InventoryOut(BaseModel):
    items: list[InventoryItemOut]


class RateOut(BaseModel):
    #: The CBU rate, soʻm per dollar; ``null`` without a fresh one.
    usd_uzs: str | None


class ItemOut(BaseModel):
    id: str
    name: str
    asset_id: str | None
    image_url: str | None
    skinslink_usd: str | None
    destination: Destination
    cost_usd: str | None
    state: str
    deposit_id: str | None
    sold_where: str | None
    sold_amount: str | None
    sold_currency: Currency | None
    sold_usd: str | None
    resolved_at: datetime | None
    note: str | None


class DepositOut(BaseModel):
    id: str
    status: str
    amount_usd: str | None
    trade_offer_id: str | None
    offer_expiry_at: str | None
    hold_end_date: str | None
    fail_reason: str | None
    accepted_at: datetime | None
    credited_at: datetime | None
    reverted_at: datetime | None
    created_at: datetime


class DealOut(BaseModel):
    id: str
    status: DealStatus
    trader: str
    note: str | None
    trade_link: str | None
    paid_amount: str | None
    paid_currency: Currency | None
    rate: str | None
    paid_usd: str | None
    method: Method
    paid_at: datetime | None
    guarantor_released_at: datetime | None
    created_at: datetime
    updated_at: datetime
    items: list[ItemOut]
    deposits: list[DepositOut]
    #: The end of Steam's 7-day protection after the trader accepted; ``null`` before.
    protected_until: datetime | None
    #: The profit booked so far (the sum of its ledger rows).
    profit_usd: str
    #: Every item credited, sold, written off or reverted: the profit is final.
    resolved: bool


class DealRowOut(BaseModel):
    id: str
    status: DealStatus
    trader: str
    method: Method
    created_at: datetime
    paid_amount: str | None
    paid_currency: Currency | None
    paid_usd: str | None
    items: int
    profit_usd: str
    resolved: bool


class DealsOut(BaseModel):
    items: list[DealRowOut]
    next_cursor: str | None


class StockItemOut(ItemOut):
    deal_id: str
    trader: str
    bought_at: datetime


class StockOut(BaseModel):
    items: list[StockItemOut]
    total_cost_usd: str


class WithdrawalOut(BaseModel):
    id: str
    amount_usd: str
    note: str | None
    at: datetime


class WithdrawalsOut(BaseModel):
    items: list[WithdrawalOut]


class SummaryOut(BaseModel):
    #: Profit booked in the window (Tashkent days, inclusive).
    profit_usd: str
    #: Skinslink money booked in the window (credits less reverts).
    revenue_usd: str
    deals_closed: int
    items_resolved: int
    #: Cost of the paid deals' items still on their way to Skinslink.
    in_transit_usd: str
    #: Cost of the skins in the owner's stock.
    stock_usd: str
    #: All-time Skinslink money of the desk less what the owner took out.
    skinslink_share_usd: str
