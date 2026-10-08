"""Customer wire shapes of ``sales``. Money travels as strings of whole soʻm."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from csmarket.modules.sales.models import PayoutCard
from csmarket.modules.sales.rules import CardType


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
