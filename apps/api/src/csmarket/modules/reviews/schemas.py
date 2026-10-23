"""Wire models of ``/reviews*`` (the user and the public page) and ``/admin/reviews*``.

Dates are ISO 8601 UTC. A public or admin review carries ``kind`` / ``locale`` as plain strings
(``market`` / ``sale``, ``ru`` / ``uz`` / ``en``): they are read back from checked columns.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from csmarket.modules.reviews.models import TEXT_MAX

KindOut = Literal["market", "sale"]
LocaleIn = Literal["ru", "uz", "en"]


def _trimmed(value: object) -> object:
    """A string trimmed, blank as ``None``; anything else as given (Pydantic reports it)."""
    if isinstance(value, str):
        return value.strip() or None
    return value


class ReviewIn(BaseModel):
    """Stars, an optional text and the interface locale the user wrote in."""

    rating: int = Field(ge=1, le=5)
    #: Trimmed before the length check; blank is no text. Stored as typed, shown as text.
    text: str | None = Field(default=None, max_length=TEXT_MAX)
    locale: LocaleIn

    @field_validator("text", mode="before")
    @classmethod
    def _trim(cls, value: object) -> object:
        """Trim first, so trailing spaces never push a text over the limit."""
        return _trimmed(value)


class DealOut(BaseModel):
    """The deal the prompt asks about."""

    kind: KindOut
    number: str
    #: The skin's name; for a sale, its most valuable item.
    title: str
    image_url: str | None
    #: How many items (1 for an order).
    items: int
    #: When the deal succeeded (rule 7).
    done_at: datetime


class PendingOut(BaseModel):
    """The newest deal to review now, or ``null``."""

    deal: DealOut | None


class MyReviewOut(BaseModel):
    """My review as I wrote it."""

    rating: int
    text: str | None
    locale: str
    created_at: datetime
    updated_at: datetime


class DealReviewOut(BaseModel):
    """A deal of mine and my review of it."""

    kind: KindOut
    number: str
    #: It may be reviewed (or the review edited) now.
    can_review: bool
    #: The last moment it may be; ``null`` while the deal has not succeeded.
    editable_until: datetime | None
    review: MyReviewOut | None
