"""Pydantic shapes of the site's API-key routes."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ApiKeyOut(BaseModel):
    """The live key's public facts (never the token)."""

    model_config = ConfigDict(frozen=True)

    id: str
    pricing_profile: str
    created_at: datetime
    last_used_at: datetime | None


class ApiKeyIssuedOut(BaseModel):
    """A freshly issued key: the token is shown this once."""

    model_config = ConfigDict(frozen=True)

    id: str
    token: str
    pricing_profile: str
    created_at: datetime


class CatalogItemOut(BaseModel):
    """One catalogue item priced for the caller's tariff (USD, three decimals)."""

    model_config = ConfigDict(frozen=True)

    item_id: str
    slug: str
    market_hash_name: str
    exterior: str | None
    price_usd: str
    #: Only on the ``cost`` tariff; the key is omitted otherwise.
    retail_price_usd: str | None = None
    stock: int
    updated_at: datetime | None


class CatalogPageOut(BaseModel):
    """A page of the catalogue feed."""

    model_config = ConfigDict(frozen=True)

    items: list[CatalogItemOut]
    next_cursor: str | None


class OfferOut(BaseModel):
    """One purchasable offer; ``offer_id`` is opaque and bound to its item."""

    model_config = ConfigDict(frozen=True, populate_by_name=True)

    offer_id: str
    float_value: float | None = Field(alias="float")
    paint_seed: int | None
    # Any: sticker objects as the storefront shows them (name, image, slot, wear).
    stickers: list[dict[str, Any]]
    price_usd: str
    #: Only on the ``cost`` tariff; the key is omitted otherwise.
    retail_price_usd: str | None = None
    delivery: Literal["instant"]


__all__ = ["ApiKeyIssuedOut", "ApiKeyOut", "CatalogItemOut", "CatalogPageOut", "OfferOut"]
