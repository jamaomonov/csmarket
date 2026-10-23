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


class ReviewPendingOut(BaseModel):
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


class PublicReviewOut(BaseModel):
    """A published review as the public page shows it: no Steam ID, email, number or amount."""

    id: str
    #: The author's Steam display name and avatar (public on Steam).
    author_name: str | None
    author_avatar_url: str | None
    rating: int
    text: str | None
    #: ``market`` or ``sale``.
    kind: str
    #: The skin (``market``); ``null`` for a sale (the page says «Продажа скинов»).
    skin_name: str | None
    #: ``ru`` / ``uz`` / ``en``: the interface the author wrote in.
    locale: str
    created_at: datetime


class PublicReviewsOut(BaseModel):
    """The public page: off, or the published reviews and their count (no average)."""

    enabled: bool
    count: int
    items: list[PublicReviewOut]
    next_cursor: str | None


class ReviewAdminUserOut(BaseModel):
    """A user as the admin's lists name them."""

    id: str
    display_name: str | None
    avatar_url: str | None
    email_confirmed: bool = Field(
        description="A confirmed email to answer a bad review at (the address is on the user page)."
    )


class AdminReviewOut(BaseModel):
    """One review in the admin's «Отзывы»."""

    id: str
    #: ``market`` or ``sale``.
    kind: str
    #: The order's or the sale's number.
    number: str
    rating: int
    text: str | None
    locale: str
    hidden: bool
    #: Shown on the public page once it is on: good and not hidden.
    published: bool
    user: ReviewAdminUserOut
    created_at: datetime
    updated_at: datetime
    resolved_at: datetime | None
    resolved_by: ReviewAdminUserOut | None
    resolved_note: str | None


class AdminReviewsPage(BaseModel):
    """A page of reviews."""

    items: list[AdminReviewOut]
    next_cursor: str | None
    #: Unresolved bad reviews, whatever the tab and filters («Плохие N»).
    bad_open: int


class ReviewResolveIn(BaseModel):
    """«Разобрано»: what the admin did."""

    note: str = Field(min_length=1, max_length=500)

    @field_validator("note", mode="before")
    @classmethod
    def _trim(cls, value: object) -> object:
        """A blank note is no note (422)."""
        return _trimmed(value)


class ReviewSettingsIn(BaseModel):
    """«Показывать отзывы на сайте»."""

    reviews_public: bool


class ReviewSettingsOut(BaseModel):
    """The switch, how many reviews it would show, and who set it last."""

    reviews_public: bool
    published_count: int
    updated_at: datetime | None
    updated_by: ReviewAdminUserOut | None
