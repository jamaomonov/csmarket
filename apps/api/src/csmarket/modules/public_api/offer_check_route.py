"""``GET /api/v1/public/catalog/{item_id}/offers/{offer_id}`` — check one offer before charging.

A partner takes its buyer's money first and buys from us after, so it asks here right before
the payment: a sold offer is ``gone`` and its buyer is never charged for it (ADR-0017,
2026-10-10). The ``check`` limit of the key (30 a minute by default).
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.api.v1.deps import db_session
from csmarket.core.clock import now
from csmarket.core.config import Settings, get_settings
from csmarket.core.errors import NotFoundError
from csmarket.core.money import wire_usd
from csmarket.core.redis import get_redis
from csmarket.modules.lisskins.api import AvailabilityClient, availability_client, snapshot_fresh
from csmarket.modules.public_api.auth import ApiCaller, api_caller
from csmarket.modules.public_api.limits import enforce
from csmarket.modules.public_api.metering import MeteredRoute
from csmarket.modules.public_api.offer_check import live_quote
from csmarket.modules.public_api.offers import api_offers, open_offer_id
from csmarket.modules.public_api.schemas import OfferCheckOut
from csmarket.modules.skins.api import enabled_categories, get_item_by_id, load_rules
from csmarket.modules.skinslink.api import mirror_age, mirror_fresh

router = APIRouter(prefix="/public", tags=["public-api"], route_class=MeteredRoute)

_ERRORS: dict[int | str, dict[str, Any]] = {
    401: {"description": "`unauthorized`"},
    403: {"description": "`account_suspended`, `ip_not_allowed`"},
    404: {"description": "`item_not_found`, `offer_not_found` (a forged or foreign offer_id)"},
    429: {"description": "`rate_limited`, with `Retry-After`"},
}


async def _source_fresh(
    db: AsyncSession, internal: str, *, settings: Settings, at: datetime
) -> bool:
    """Whether the offer's source is read fresh, so its missing offer was really sold."""
    if internal.startswith("sl:"):
        return await mirror_fresh(db, settings=settings, now=at)
    if internal.startswith("ls:"):
        return await snapshot_fresh(db, settings=settings, now=at)
    return True


@router.get(
    "/catalog/{item_id}/offers/{offer_id}",
    response_model=OfferCheckOut,
    summary="Check one offer before you charge your buyer",
    responses=_ERRORS,
)
async def check_offer(
    item_id: str,
    offer_id: str,
    caller: Annotated[ApiCaller, Depends(api_caller)],
    db: Annotated[AsyncSession, Depends(db_session)],
    availability: Annotated[AvailabilityClient, Depends(availability_client)],
) -> JSONResponse:
    """Whether the offer is still for sale and its price for your tariff, asked live.

    Call it right before you take your buyer's money. ``gone``: the offer was sold, pick
    another one. ``unconfirmed``: the market did not answer in time; ``price_usd`` is the last
    known price and ``POST /orders`` checks again. A sold offer is never replaced by another.
    Not cached; counts against the key's ``check`` limit.
    """
    await enforce(caller, "check")
    settings = get_settings()
    profile = caller.key.pricing_profile
    item = await get_item_by_id(db, item_id, categories=enabled_categories(settings))
    if item is None:
        raise NotFoundError("no such item", code="item_not_found")
    internal = open_offer_id(offer_id, item.id)
    if internal is None:
        raise NotFoundError("no such offer", code="offer_not_found")
    at = now()
    priced = await api_offers(db, item, profile=profile, settings=settings, now=at)
    offer = next((p for p in priced if p.offer.offer_id == internal), None)
    if offer is None:
        # Gone from a source we read fresh: sold, no call. From a stale one: we cannot tell.
        fresh = await _source_fresh(db, internal, settings=settings, at=at)
        return JSONResponse(
            {"offer_id": offer_id, "status": "gone" if fresh else "unconfirmed", "price_usd": None}
        )
    age = await mirror_age(db, now=at)
    rules = await load_rules(db)
    db.expunge_all()
    await db.rollback()  # no connection held across LIS-SKINS (AGENTS §11)
    status, quoted = await live_quote(
        offer,
        item=item,
        rules=rules,
        profile=profile,
        redis=get_redis(),
        client=availability if settings.lisskins_active else None,
        mirror_age=age,
    )
    if quoted is None:
        return JSONResponse({"offer_id": offer_id, "status": status, "price_usd": None})
    out: dict[str, Any] = {
        "offer_id": offer_id,
        "status": status,
        "price_usd": wire_usd(quoted.price_units),
    }
    if profile == "cost":
        out["retail_price_usd"] = wire_usd(quoted.retail_units)
    return JSONResponse(out)
