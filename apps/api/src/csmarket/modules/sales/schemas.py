"""Customer wire shapes of ``sales``. Money travels as strings of whole soʻm."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from csmarket.modules.sales.models import PayoutCard
from csmarket.modules.sales.rules import CardType, PayoutTo, SaleSettings


class CardOut(BaseModel):
    """A saved card: its type and last four digits, never the number."""

    id: str
    type: CardType
    last4: str
    created_at: datetime

    @classmethod
    def of(cls, card: PayoutCard) -> CardOut:
        """Build from a row."""
        return cls(
            id=card.id,
            type=card.type,  # type: ignore[arg-type]  # the column's check admits only CardType
            last4=card.last4,
            created_at=card.created_at,
        )


class CardsOut(BaseModel):
    """The user's live cards, oldest first."""

    items: list[CardOut]


def plain(value: Decimal) -> str:
    """A percent or a price without trailing zeros or an exponent: ``2``, ``1.5``."""
    text = format(value.normalize(), "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


class SellConfigOut(BaseModel):
    """What the sell page shows before anything is chosen (public)."""

    enabled: bool
    balance_bonus_pct: str
    card_fee_pct: dict[CardType, str]
    #: Whole soʻm.
    card_min_uzs: str
    #: The minimum sum in soʻm, a hint (the API decides on the USD sum); ``null`` without a rate.
    min_sum_uzs: str | None
    max_cards: int

    @classmethod
    def of(
        cls, doc: SaleSettings, *, enabled: bool, min_sum_uzs: str | None, max_cards: int
    ) -> SellConfigOut:
        """Build from the settings document."""
        fees = doc.card_fee_pct
        return cls(
            enabled=enabled,
            balance_bonus_pct=plain(doc.balance_bonus_pct),
            card_fee_pct={
                "uzcard": plain(fees.uzcard),
                "humo": plain(fees.humo),
                "uzum_visa": plain(fees.uzum_visa),
            },
            card_min_uzs=str(doc.card_min_uzs),
            min_sum_uzs=min_sum_uzs,
            max_cards=max_cards,
        )


class SellItemOut(BaseModel):
    """One item the seller can sell now, at our price."""

    asset_id: str
    #: Steam's market name; skin names stay English.
    name: str
    image_url: str | None
    exterior: str | None
    rarity_color: str | None
    #: Our catalogue's category for the filter chips; ``null`` when we do not list the item.
    category: str | None
    price_uzs: str


class InventoryOut(BaseModel):
    """The priced inventory; ``max_items`` is the most one sale may carry."""

    items: list[SellItemOut]
    max_items: int
    min_sum_uzs: str
    fetched_at: datetime


#: A Steam trade offer's page.
OFFER_URL = "https://steamcommunity.com/tradeoffer/{id}/"

SaleStatusOut = Literal["creating", "offered", "hold", "credited", "payout", "closed", "reverted"]
PayoutStatusOut = Literal["waiting_hold", "to_pay", "paid", "rejected", "canceled"]


class NewCardIn(BaseModel):
    """A card typed in the cart. PII: ``number`` never appears in a repr or a log."""

    type: CardType
    #: Digits; spaces and dashes allowed. Checked by the service (``card_invalid``).
    number: str = Field(min_length=12, max_length=32, repr=False)


class PayoutIn(BaseModel):
    """Where the money goes: the balance, a saved card, or a new card."""

    to: PayoutTo
    card_id: uuid.UUID | None = None
    new_card: NewCardIn | None = None

    @model_validator(mode="after")
    def _one_target(self) -> PayoutIn:
        cards = (self.card_id is not None) + (self.new_card is not None)
        if self.to == "balance" and cards:
            raise ValueError("a payout to the balance takes no card")
        if self.to == "card" and cards != 1:
            raise ValueError("a card payout takes card_id or new_card, one of them")
        return self


class SellIn(BaseModel):
    """``POST /sell``: the chosen asset ids, where the money goes, the payout the cart showed."""

    asset_ids: list[str] = Field(min_length=1, max_length=200)
    payout: PayoutIn
    #: Whole soʻm the cart showed; another server figure is 409 ``prices_changed``.
    expected_payout_uzs: int = Field(ge=0)


class SaleItemOut(BaseModel):
    """An item of a sale at the price the seller saw."""

    asset_id: str
    name: str
    image_url: str | None
    price_uzs: str


class SaleCardOut(BaseModel):
    """The card a sale pays to."""

    type: CardType
    last4: str


class SaleOfferOut(BaseModel):
    """The Steam offer to accept, while the sale is ``offered``."""

    url: str
    bot_name: str | None
    expires_at: datetime | None


class SaleOut(BaseModel):
    """A sale as its seller sees it. Money in whole soʻm, as strings."""

    number: str
    status: SaleStatusOut
    payout_to: PayoutTo
    card: SaleCardOut | None
    items_uzs: str
    bonus_uzs: str
    fee_uzs: str
    payout_uzs: str
    items: list[SaleItemOut]
    offer: SaleOfferOut | None
    #: When the money is due (while ``hold``).
    money_at: datetime | None
    #: A card sale's payout request, once there is one.
    payout_status: PayoutStatusOut | None
    created_at: datetime
