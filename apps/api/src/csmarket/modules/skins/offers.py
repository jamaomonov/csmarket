"""Source-neutral offers (spec 2026-10-06 §4): what the item page lists and checkout buys.

An offer id names its market: ``wx:<Waxpeer item_id>`` or ``sl:<Skinslink offer id>`` (a
Steam asset id, or a hex id for an offer Skinslink holds in stock); a bare
integer is read as Waxpeer's for one release (an open tab from before the change). The
customer never sees the source — only the id the buy panel echoes back.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from csmarket.modules.skins.listings import Listing

Source = Literal["waxpeer", "skinslink"]
_PREFIX: dict[str, Source] = {"wx": "waxpeer", "sl": "skinslink"}
_PREFIX_OF: dict[Source, str] = {"waxpeer": "wx", "skinslink": "sl"}
#: Waxpeer's listing ids are integers.
_WAXPEER_ID = re.compile(r"[0-9]{1,20}")
#: Skinslink's offer id: a Steam asset id, or a lowercase hex id for an offer held in stock
#: (up to ~270 characters as of 2026-10-07; ``MAX_SKINSLINK_ID`` bounds it).
MAX_SKINSLINK_ID = 300
_SKINSLINK_ID = re.compile(rf"[0-9a-f]{{1,{MAX_SKINSLINK_ID}}}")


@dataclass(frozen=True)
class Offer:
    """One offer of either source, in units (1000 = $1)."""

    offer_id: str
    source: Source
    price_units: int
    float_value: float | None
    paint_seed: int | None
    # Any: sticker objects as ``listings._sticker`` keeps them (scalars only).
    stickers: list[dict[str, Any]] = field(default_factory=list)
    inspect_url: str | None = None
    #: The Waxpeer listing (``source == "waxpeer"``).
    listing_id: int | None = None
    #: The Skinslink item / Steam asset (``source == "skinslink"``).
    asset_id: str | None = None


def offer_id_of(source: Source, raw: int | str) -> str:
    """``wx:123`` / ``sl:380…``."""
    return f"{_PREFIX_OF[source]}:{raw}"


def parse_offer_id(value: str | int) -> tuple[Source, str]:
    """``(source, raw id)`` of an offer id; a bare positive integer is Waxpeer's.

    Raises:
        ValueError: An unknown prefix, an empty or non-numeric id, or a non-positive integer.
    """
    text = str(value)
    if text.isdigit():
        if int(text) <= 0:
            raise ValueError(f"not an offer id: {text!r}")
        return "waxpeer", text
    prefix, sep, raw = text.partition(":")
    source = _PREFIX.get(prefix)
    pattern = _SKINSLINK_ID if source == "skinslink" else _WAXPEER_ID
    if not sep or source is None or not pattern.fullmatch(raw):
        raise ValueError(f"not an offer id: {text!r}")
    return source, raw


def from_listing(listing: Listing) -> Offer:
    """A Waxpeer auto listing as an offer."""
    return Offer(
        offer_id=offer_id_of("waxpeer", listing.listing_id),
        source="waxpeer",
        price_units=listing.price_units,
        float_value=listing.float_value,
        paint_seed=listing.paint_seed,
        stickers=listing.stickers,
        inspect_url=listing.inspect_url,
        listing_id=listing.listing_id,
    )


def merge_offers(*groups: Sequence[Offer]) -> list[Offer]:
    """Every group's offers by price; Waxpeer first on a tie (its delivery is instant)."""
    return sorted(
        (o for group in groups for o in group),
        key=lambda o: (o.price_units, o.source != "waxpeer", o.offer_id),
    )


__all__ = [
    "MAX_SKINSLINK_ID",
    "Offer",
    "Source",
    "from_listing",
    "merge_offers",
    "offer_id_of",
    "parse_offer_id",
]
