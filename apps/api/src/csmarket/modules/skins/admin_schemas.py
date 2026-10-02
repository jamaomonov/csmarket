"""DTOs for ``/admin/skins/*``: catalogue status, item search, hide, search aliases.

Money is a string in transit. Nothing here carries a secret (the Waxpeer key is reported
only as set or not) or a person.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from csmarket.modules.skins.pricing import PricingRules


class JobOut(BaseModel):
    """The last run of a catalogue job (ruling Q6)."""

    finished_at: datetime
    ok: bool
    counters: dict[str, int]
    #: Our own short label for the failure, never upstream text.
    error: str | None


class FxOut(BaseModel):
    """The CBU rate the catalogue prices with."""

    usd_uzs: str
    fetched_at: datetime
    source: str


class CatalogStatusOut(BaseModel):
    """The admin status card: catalogue size, job outcomes, rate and switches."""

    items_total: int
    #: Priced with at least one auto listing (hidden ones included).
    items_active: int
    items_hidden: int
    #: The newest price tick across the catalogue.
    prices_updated_at: datetime | None
    import_job: JobOut | None
    price_sync_job: JobOut | None
    #: ``None`` without a rate younger than ``CSMARKET_FX_MAX_AGE_DAYS``.
    fx: FxOut | None
    #: ``CSMARKET_SKINS_SYNC_ENABLED`` — whether the scheduler imports and prices.
    sync_enabled: bool
    #: Whether a Waxpeer key is configured; the key itself never leaves the server.
    waxpeer_key_set: bool


class AdminSkinItemOut(BaseModel):
    """One row of the admin item search."""

    slug: str
    name: str
    phase: str | None
    category: str
    weapon: str | None
    exterior: str | None
    stattrak: bool
    souvenir: bool
    image_url: str | None
    active: bool
    hidden: bool
    #: Our stored sell price; ``None`` while sold out.
    price_usd: str | None
    count: int
    #: The cheapest auto listing at Waxpeer (what a sale costs us); ``None`` while sold out.
    cost_usd: str | None = None
    #: Percentage points added to this item's margin; ``None`` = the rules alone.
    margin_override_pp: str | None = None
    #: A pinned sell price, honoured while it covers cost + min margin.
    fixed_price_usd: str | None = None


class AdminSkinItemsOut(BaseModel):
    """Admin item search results (no paging: narrow the query instead)."""

    items: list[AdminSkinItemOut]


class AdminSkinItemPatchIn(BaseModel):
    """Hide (``true``) or show (``false``) an item everywhere public (ruling Q4)."""

    hidden: bool


#: An alias's expansion: trimmed, lower-cased, 1..128 characters.
AliasText = Annotated[
    str, StringConstraints(strip_whitespace=True, to_lower=True, min_length=1, max_length=128)
]


class AliasIn(BaseModel):
    """The text an alias expands to («ак» -> ``ak-47``)."""

    text: AliasText


class AliasOut(BaseModel):
    """One search alias."""

    alias: str
    text: str


class AliasesOut(BaseModel):
    """Every search alias, ordered by alias."""

    items: list[AliasOut]


class UpdatedByOut(BaseModel):
    """The admin who saved the rules last."""

    id: str
    display_name: str | None


class PricingOut(BaseModel):
    """The pricing document and what it prices."""

    rules: PricingRules
    updated_at: datetime | None
    updated_by: UpdatedByOut | None
    items_active: int
    #: Items with a margin override or a pinned price.
    items_overridden: int
    #: The CBU rate prices are shown in soʻm with; ``None`` without a fresh one.
    rate_uzs: str | None


class PreviewIn(BaseModel):
    """What to price: an item by ``slug``, or a made-up one by ``cost_usd`` + ``category``.

    Each field given overrides the item's own; ``rules`` previews an unsaved document.
    """

    model_config = ConfigDict(extra="forbid")

    rules: PricingRules | None = None
    slug: str | None = Field(default=None, max_length=255)
    cost_usd: Decimal | None = Field(default=None, gt=0, le=100000, decimal_places=3)
    category: str | None = Field(default=None, max_length=32)
    weapon: str | None = Field(default=None, max_length=64)
    count_auto: int | None = Field(default=None, ge=0)
    item_pp: Decimal | None = Field(default=None, ge=-100, le=500, decimal_places=2)
    fixed_price_usd: Decimal | None = Field(default=None, ge=0, le=100000, decimal_places=2)

    @model_validator(mode="after")
    def _what(self) -> Self:
        if self.slug is None and (self.cost_usd is None or self.category is None):
            raise ValueError("give a slug, or cost_usd and category")
        return self


class PreviewOut(BaseModel):
    """A quote and every component behind it (USD and soʻm as strings)."""

    price_usd: str
    #: ``None`` without a fresh CBU rate.
    price_uzs: str | None
    cost_usd: str
    expenses_usd: str
    bracket_margin_usd: str
    category_pp: str
    weapon_pp: str
    liquidity_pp: str
    item_pp: str
    effective_percent: str
    #: The last rule that set the number: formula, fixed, min_margin, steam_cap or floor.
    applied: str


class ItemPricingIn(BaseModel):
    """One item's pricing overrides; ``null`` clears one."""

    model_config = ConfigDict(extra="forbid")

    margin_override_pp: Decimal | None = Field(ge=-100, le=500, decimal_places=2)
    fixed_price_usd: Decimal | None = Field(ge=0, le=100000, decimal_places=2)


__all__ = [
    "AdminSkinItemOut",
    "AdminSkinItemPatchIn",
    "AdminSkinItemsOut",
    "AliasIn",
    "AliasOut",
    "AliasText",
    "AliasesOut",
    "CatalogStatusOut",
    "FxOut",
    "ItemPricingIn",
    "JobOut",
    "PreviewIn",
    "PreviewOut",
    "PricingOut",
    "UpdatedByOut",
]
