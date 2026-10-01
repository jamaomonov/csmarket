"""DTOs for ``/admin/skins/*``: catalogue status, item search, hide, search aliases.

Money is a string in transit. Nothing here carries a secret (the Waxpeer key is reported
only as set or not) or a person.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, StringConstraints


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
    "JobOut",
]
