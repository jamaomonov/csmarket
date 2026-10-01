"""Public DTOs for the skins catalogue. Money is a string in transit.

Nothing here names Waxpeer: listing ids and prices are ours to show, the
upstream is not.
"""

from __future__ import annotations

from pydantic import BaseModel


class SkinItemOut(BaseModel):
    """One catalogue card."""

    slug: str
    name: str
    phase: str | None
    category: str
    weapon: str | None
    skin: str | None
    exterior: str | None
    stattrak: bool
    souvenir: bool
    rarity: str | None
    rarity_color: str | None
    image_url: str | None
    #: Our sell price for the cheapest auto listing; ``None`` when sold out.
    price_usd: str | None
    #: ``price_usd`` in soʻm at the CBU rate; ``None`` without a fresh rate (ruling Q3).
    price_uzs: str | None
    steam_price_usd: str | None
    discount_percent: int | None
    count: int
    min_float: str | None
    max_float: str | None


class SkinsPageOut(BaseModel):
    """A catalogue page and the cursor for the next (``None`` on the last)."""

    items: list[SkinItemOut]
    next_cursor: str | None


class FacetOut(BaseModel):
    """A facet value and how many on-sale items carry it."""

    value: str
    count: int


class RarityFacetOut(FacetOut):
    """A rarity facet with the game's colour for that grade."""

    color: str | None = None


class SkinFacetsOut(BaseModel):
    """Counts per category, weapon, wear, rarity and (for agents) side."""

    categories: list[FacetOut]
    weapons: list[FacetOut]
    exteriors: list[FacetOut]
    rarities: list[RarityFacetOut]
    #: An agent's side (``ct`` / ``t``); empty outside a category that has sides.
    teams: list[FacetOut] = []


class SkinSuggestOut(BaseModel):
    """Search-as-you-type results."""

    items: list[SkinItemOut]


class SkinListingSummaryOut(BaseModel):
    """One of the cheapest auto listings from the last price tick, at our price."""

    listing_id: int
    price_usd: str
    price_uzs: str | None


class SkinFamilyMemberOut(BaseModel):
    """Another wear (or StatTrak/Souvenir twin) of the same skin."""

    slug: str
    exterior: str | None
    stattrak: bool
    souvenir: bool
    price_usd: str | None
    price_uzs: str | None
    count: int


class SkinDetailOut(SkinItemOut):
    """The item page: the card plus its cheapest listings and its family."""

    cheapest: list[SkinListingSummaryOut]
    family: list[SkinFamilyMemberOut]
    #: Buying is switched on (``skins_buy_enabled``): show the buy panel.
    buy_enabled: bool


class SkinStickerOut(BaseModel):
    """A sticker applied to a live listing."""

    name: str
    image: str | None
    slot: int | None
    wear: float | None


class SkinListingOut(BaseModel):
    """One live auto listing at our price."""

    listing_id: int
    price_usd: str
    price_uzs: str | None
    float_value: float | None
    paint_seed: int | None
    stickers: list[SkinStickerOut]
    inspect_url: str | None


class SkinListingsOut(BaseModel):
    """Live listings for one item."""

    items: list[SkinListingOut]
    #: ``True`` when the answer is a stale cache or the snapshot, not a live read.
    degraded: bool


class SkinSlugsOut(BaseModel):
    """A page of item slugs on sale, and how many there are."""

    items: list[str]
    total: int


__all__ = [
    "FacetOut",
    "RarityFacetOut",
    "SkinDetailOut",
    "SkinFacetsOut",
    "SkinFamilyMemberOut",
    "SkinItemOut",
    "SkinListingOut",
    "SkinListingSummaryOut",
    "SkinListingsOut",
    "SkinSlugsOut",
    "SkinStickerOut",
    "SkinSuggestOut",
    "SkinsPageOut",
]
