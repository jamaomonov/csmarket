"""A partner's offer, confirmed live before money changes hands (ADR-0017, 2026-10-10).

Both ``POST /public/orders`` and ``GET /public/catalog/{item_id}/offers/{offer_id}`` use
:func:`live_quote`. A LIS-SKINS lot is asked ``check-availability`` once, in the partner API's
own budget share, so partners never spend the storefront's. A Skinslink offer answers from the
mirror (≤ 15 s old) with no call. A changed price is re-quoted for the key's tariff. A sold lot
is never replaced by another one (ADR-0013).
"""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from typing import Literal

from redis.asyncio import Redis

from csmarket.core.logging import get_logger
from csmarket.modules.lisskins.api import AvailabilityClient, live_price
from csmarket.modules.public_api.offers import PricedOffer, price_units_for
from csmarket.modules.skins.api import PricingRules, SkinItem, parse_offer_id

log = get_logger("csmarket.public_api.offer_check")

#: A Skinslink offer from a mirror synced within this long counts as checked; an older one is
#: ``unconfirmed`` (the mirror follows Skinslink's change feed every 15 s).
MIRROR_CHECKED = timedelta(seconds=30)

#: ``available``: for sale at the quoted price. ``gone``: sold. ``unconfirmed``: LIS-SKINS
#: did not answer — the snapshot price stands and the order re-checks.
OfferStatus = Literal["available", "gone", "unconfirmed"]


async def live_quote(
    offer: PricedOffer,
    *,
    item: SkinItem,
    rules: PricingRules,
    profile: str,
    redis: Redis,
    client: AvailabilityClient | None,
    mirror_age: timedelta | None = None,
) -> tuple[OfferStatus, PricedOffer | None]:
    """``(status, the offer at its live price)``; ``None`` when ``gone``.

    ``mirror_age``: how old the Skinslink mirror is — a Skinslink offer is ``available`` only
    from a mirror synced within :data:`MIRROR_CHECKED`, else ``unconfirmed``.

    Holds no DB connection: the caller releases it first (AGENTS §11).
    """
    if offer.offer.source == "skinslink":
        fresh = mirror_age is not None and mirror_age <= MIRROR_CHECKED
        return ("available" if fresh else "unconfirmed"), offer
    if client is None or offer.offer.source != "lisskins":
        return "available", offer
    verdict, units = await live_price(
        redis, client, int(parse_offer_id(offer.offer.offer_id)[1]), scope="api"
    )
    log.info("public_api.offer_check", verdict=verdict)
    if verdict == "gone":
        return "gone", None
    if verdict == "unknown" or units is None:
        return "unconfirmed", offer
    if units == offer.offer.price_units:
        return "available", offer
    price, retail = price_units_for(
        units, profile=profile, item=item, rules=rules, stock=item.stock_count
    )
    return "available", PricedOffer(
        replace(offer.offer, price_units=units), price, retail, offer.public_id
    )


__all__ = ["MIRROR_CHECKED", "OfferStatus", "live_quote"]
