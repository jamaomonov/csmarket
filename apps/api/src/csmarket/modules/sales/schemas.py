"""Customer wire shapes of ``sales``. Money travels as strings of whole soʻm."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel

from csmarket.modules.sales.models import PayoutCard
from csmarket.modules.sales.rules import CardType, SaleSettings


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
