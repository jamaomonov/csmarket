"""``/api/v1/public`` -- the partner API, authenticated by ``Authorization: Bearer csm_…``.

Catalogue: a paged feed read from the Redis snapshot (:mod:`feed`) and the offers of one
item, priced by the key's tariff. No request here calls a supplier.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Query, Response
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.api.v1.deps import db_session
from csmarket.core.clock import now
from csmarket.core.config import get_settings
from csmarket.core.errors import ConflictError, NotFoundError
from csmarket.core.money import wire_usd
from csmarket.core.redis import get_redis
from csmarket.modules.public_api import feed
from csmarket.modules.public_api.auth import ApiCaller, api_caller
from csmarket.modules.public_api.limits import enforce
from csmarket.modules.public_api.offers import PricedOffer, api_offers
from csmarket.modules.public_api.schemas import CatalogPageOut, OfferOut
from csmarket.modules.skins.api import SkinItem, enabled_categories

router = APIRouter(prefix="/public", tags=["public-api"])

OFFERS_TTL_SECONDS = 60
_REVALIDATE = {"Cache-Control": "private, no-cache"}


def _cursor_expired() -> ConflictError:
    return ConflictError(
        "this cursor has expired; restart from the first page", code="cursor_expired"
    )


def _item_out(row: dict[str, Any], profile: str) -> dict[str, Any]:
    cost = profile == "cost"
    out: dict[str, Any] = {
        "item_id": row["item_id"],
        "slug": row["slug"],
        "market_hash_name": row["market_hash_name"],
        "exterior": row["exterior"],
        "price_usd": wire_usd(row["cost_units"] if cost else row["retail_units"]),
    }
    if cost:
        out["retail_price_usd"] = wire_usd(row["retail_units"])
    out["stock"] = row["stock"]
    out["updated_at"] = row["updated_at"]
    return out


def _body_response(body: str, if_none_match: str | None) -> Response:
    """``body`` with its ETag; 304 and empty when the client already has it."""
    etag = f'"{hashlib.sha256(body.encode()).hexdigest()}"'
    headers = {**_REVALIDATE, "ETag": etag}
    if if_none_match is not None and etag in {t.strip() for t in if_none_match.split(",")}:
        return Response(status_code=304, headers=headers)
    return Response(content=body, media_type="application/json", headers=headers)


@router.get("/catalog", response_model=CatalogPageOut, summary="Catalogue feed, one page")
async def catalog(
    caller: Annotated[ApiCaller, Depends(api_caller)],
    cursor: Annotated[str | None, Query(max_length=64)] = None,
    updated_since: Annotated[datetime | None, Query()] = None,
    if_none_match: Annotated[str | None, Header()] = None,
) -> Response:
    """Page ``n`` of the current snapshot (1000 items), priced by the key's tariff.

    The first page counts against the 1 per minute ``feed`` limit, later pages against
    ``read``. A cursor of an expired snapshot answers 409 ``cursor_expired``. ``ETag`` /
    ``If-None-Match`` give a 304.
    """
    parsed = feed.parse_cursor(cursor) if cursor else None
    if cursor and parsed is None:
        raise _cursor_expired()
    page_no = parsed[1] if parsed else 0
    await enforce(caller, "feed" if page_no == 0 else "read")
    redis = get_redis()
    if parsed is None:
        raw_meta = await redis.get(feed.CURRENT_KEY)
        if raw_meta is None or int(json.loads(raw_meta)["pages"]) == 0:
            return _body_response(json.dumps({"items": [], "next_cursor": None}), if_none_match)
        snap = str(json.loads(raw_meta)["snap"])
    else:
        snap = parsed[0]
    raw = await redis.get(feed.page_key(snap, page_no))
    if raw is None:
        raise _cursor_expired()
    rows: list[dict[str, Any]] = json.loads(raw)
    if updated_since is not None:
        since = updated_since if updated_since.tzinfo else updated_since.replace(tzinfo=UTC)
        rows = [
            r
            for r in rows
            if r["updated_at"] is not None and datetime.fromisoformat(r["updated_at"]) >= since
        ]
    profile = caller.key.pricing_profile
    has_next = await redis.exists(feed.page_key(snap, page_no + 1))
    body = json.dumps(
        {
            "items": [_item_out(r, profile) for r in rows],
            "next_cursor": feed.cursor_of(snap, page_no + 1) if has_next else None,
        }
    )
    return _body_response(body, if_none_match)


def _offer_out(p: PricedOffer, profile: str) -> dict[str, Any]:
    out: dict[str, Any] = {
        "offer_id": p.public_id,
        "float": p.offer.float_value,
        "paint_seed": p.offer.paint_seed,
        "stickers": p.offer.stickers,
        "price_usd": wire_usd(p.price_units),
    }
    if profile == "cost":
        out["retail_price_usd"] = wire_usd(p.retail_units)
    out["delivery"] = "instant"
    return out


@router.get(
    "/catalog/{item_id}/offers",
    response_model=list[OfferOut],
    response_model_by_alias=True,
    summary="Offers of one item",
)
async def item_offers(
    item_id: str,
    caller: Annotated[ApiCaller, Depends(api_caller)],
    db: Annotated[AsyncSession, Depends(db_session)],
) -> Response:
    """Skinslink + LIS-SKINS offers of the item, cheapest first, priced by the key's tariff.

    Cached 60 s per tariff and item. Offer ids are opaque and bound to the item.
    """
    await enforce(caller, "read")
    profile = caller.key.pricing_profile
    redis = get_redis()
    cache_key = f"public_api:offers:{profile}:{item_id}"
    cached = await redis.get(cache_key)
    if cached is not None:
        return JSONResponse(content=json.loads(cached), headers=_REVALIDATE)
    settings = get_settings()
    stmt = select(SkinItem).where(
        SkinItem.id == item_id,
        SkinItem.active.is_(True),
        SkinItem.hidden.is_(False),
        SkinItem.category.in_(enabled_categories(settings)),
    )
    item = (await db.execute(stmt)).scalar_one_or_none()
    if item is None:
        raise NotFoundError("no such item", code="item_not_found")
    priced = await api_offers(db, item, profile=profile, settings=settings, now=now())
    out = [_offer_out(p, profile) for p in priced]
    await redis.set(cache_key, json.dumps(out), ex=OFFERS_TTL_SECONDS)
    return JSONResponse(content=out, headers=_REVALIDATE)
