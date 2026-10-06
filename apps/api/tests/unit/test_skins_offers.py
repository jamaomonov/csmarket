"""Source-neutral offers: prefixed ids, the merge order, a Waxpeer listing as an offer."""

from __future__ import annotations

import pytest
from csmarket.modules.skins.listings import Listing
from csmarket.modules.skins.offers import (
    Offer,
    Source,
    from_listing,
    merge_offers,
    offer_id_of,
    parse_offer_id,
)


def _o(source: Source, price: int, raw: str) -> Offer:
    return Offer(
        offer_id=offer_id_of(source, raw),
        source=source,
        price_units=price,
        float_value=None,
        paint_seed=None,
        stickers=[],
        inspect_url=None,
    )


def test_ids_round_trip() -> None:
    assert offer_id_of("waxpeer", 123) == "wx:123"
    assert offer_id_of("skinslink", "38029384123") == "sl:38029384123"
    assert parse_offer_id("wx:123") == ("waxpeer", "123")
    assert parse_offer_id("sl:38029384123") == ("skinslink", "38029384123")
    assert parse_offer_id(123) == ("waxpeer", "123")  # one release of the old integer
    assert parse_offer_id("123") == ("waxpeer", "123")


@pytest.mark.parametrize("bad", ["ebay:1", "wx:", "sl:", "wx:abc", "", "x", "sl:1:2", -5, 0])
def test_bad_ids_are_refused(bad: str | int) -> None:
    with pytest.raises(ValueError, match="offer id"):
        parse_offer_id(bad)


def test_merge_sorts_by_price_then_waxpeer_first() -> None:
    merged = merge_offers(
        [_o("waxpeer", 1200, "2"), _o("waxpeer", 1000, "1")],
        [_o("skinslink", 1000, "8"), _o("skinslink", 900, "9")],
    )
    assert [o.offer_id for o in merged] == ["sl:9", "wx:1", "sl:8", "wx:2"]


def test_from_listing_keeps_the_fields() -> None:
    listing = Listing(
        listing_id=7,
        price_units=5000,
        float_value=0.1,
        paint_seed=3,
        stickers=[{"name": "s"}],
        inspect_url="steam://x",
        delivery=None,
    )
    o = from_listing(listing)
    assert (o.offer_id, o.source, o.listing_id, o.price_units, o.stickers) == (
        "wx:7",
        "waxpeer",
        7,
        5000,
        [{"name": "s"}],
    )
    assert o.asset_id is None
