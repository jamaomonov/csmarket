"""``/api/v1/public`` -- the partner API, authenticated by ``Authorization: Bearer csm_…``.

Catalogue: a paged feed read from the Redis snapshot (:mod:`feed`) and the offers of one
item, priced by the key's tariff. Buying: ``POST /orders`` pays from the USD wallet in one
transaction (``orders.api_checkout``); the owner's API orders (any of their keys) read through
``orders.public_view``; ``/me`` shows the balance, the key and its limits. No request here
calls a market.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Annotated, Any
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Header, Query, Response
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.api.v1.deps import db_session
from csmarket.core.clock import now
from csmarket.core.config import get_settings
from csmarket.core.errors import AppError, ConflictError, NotFoundError, PaymentRequiredError
from csmarket.core.idempotency import load_replay, require_idempotency_key, save_replay
from csmarket.core.money import wire_usd
from csmarket.core.redis import get_redis
from csmarket.modules.orders.api import create_api_order, get_for_owner, list_for_owner
from csmarket.modules.public_api import feed, webhooks
from csmarket.modules.public_api.auth import ApiCaller, api_caller
from csmarket.modules.public_api.limits import LIMITS, enforce
from csmarket.modules.public_api.offers import PricedOffer, api_offers
from csmarket.modules.public_api.schemas import (
    ApiOrderIn,
    CatalogPageOut,
    MeKeyOut,
    MeLimitsOut,
    MeOut,
    OfferOut,
    PublicOrderOut,
    PublicOrdersPage,
    PublicOrderStatus,
    WebhookIn,
    WebhookOut,
)
from csmarket.modules.public_api.webhook_url import check_url, public_addresses
from csmarket.modules.skins.api import enabled_categories, get_item_by_id
from csmarket.modules.wallet.api import InsufficientBalanceError, user_usd_balance

router = APIRouter(prefix="/public", tags=["public-api"])

OFFERS_TTL_SECONDS = 60
_REVALIDATE = {"Cache-Control": "private, no-cache"}


class FeedUnavailableError(AppError):
    """No snapshot yet (or it lapsed): the feed must not read as an empty catalogue."""

    status_code = 503
    type_uri = "https://csmarket.uz/errors/feed-unavailable"
    title = "Feed unavailable"


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


_AUTH_ERRORS: dict[int | str, dict[str, Any]] = {
    401: {"description": "`unauthorized`"},
    403: {"description": "`account_suspended`, `ip_not_allowed`"},
    429: {"description": "`rate_limited`, with `Retry-After`"},
}
_FEED_ERRORS: dict[int | str, dict[str, Any]] = {
    **_AUTH_ERRORS,
    304: {"description": "`If-None-Match` matched the page's ETag; empty body"},
    409: {"description": "`cursor_expired` -- restart from the first page"},
    503: {"description": "`feed_unavailable` -- no snapshot yet, with `Retry-After`"},
}


@router.get(
    "/catalog",
    response_model=CatalogPageOut,
    summary="Catalogue feed, one page",
    responses=_FEED_ERRORS,
)
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
        if raw_meta is None:
            raise FeedUnavailableError(
                "the catalogue feed is not ready; retry shortly",
                code="feed_unavailable",
                retry_after=60,
            )
        if int(json.loads(raw_meta)["pages"]) == 0:
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
    responses={**_AUTH_ERRORS, 404: {"description": "`item_not_found`"}},
)
async def item_offers(
    item_id: str,
    caller: Annotated[ApiCaller, Depends(api_caller)],
    db: Annotated[AsyncSession, Depends(db_session)],
) -> Response:
    """Offers of the item, cheapest first, priced by the key's tariff.

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
    item = await get_item_by_id(db, item_id, categories=enabled_categories(settings))
    if item is None:
        raise NotFoundError("no such item", code="item_not_found")
    priced = await api_offers(db, item, profile=profile, settings=settings, now=now())
    out = [_offer_out(p, profile) for p in priced]
    await redis.set(cache_key, json.dumps(out), ex=OFFERS_TTL_SECONDS)
    return JSONResponse(content=out, headers=_REVALIDATE)


_ORDER_ERRORS: dict[int | str, dict[str, Any]] = {
    **_AUTH_ERRORS,
    402: {"description": "`insufficient_balance` -- nothing was written"},
    403: {"description": "`usd_wallet_disabled`, `account_suspended`, `ip_not_allowed`"},
    404: {"description": "`item_not_found`"},
    409: {
        "description": "`offer_gone`, `price_above_max` (+ `price_usd`), `buying_disabled`, "
        "`duplicate_client_order_id` (+ `order`: the order already placed under the id)"
    },
    422: {"description": "`trade_link_invalid` and body errors"},
    503: {"description": "`rate_unavailable` -- no rate snapshot was ever recorded"},
}


@router.post(
    "/orders",
    response_model=PublicOrderOut,
    status_code=201,
    summary="Buy one skin from the USD wallet",
    responses=_ORDER_ERRORS,
)
async def place_order(
    body: ApiOrderIn,
    caller: Annotated[ApiCaller, Depends(api_caller)],
    db: Annotated[AsyncSession, Depends(db_session)],
) -> PublicOrderOut:
    """Buy the offer ``offer_id`` of ``item_id`` (else its cheapest within ``max_price_usd``).

    One transaction: the USD wallet is debited and the order is already paid on 201 (status
    ``buying``). A ``client_order_id`` already used by this account (with this key or an earlier
    one) writes nothing and answers 409
    ``duplicate_client_order_id`` with that order in ``order``. Counts against the
    10 per minute ``order`` limit.
    """
    await enforce(caller, "order")
    user_id = caller.user.id
    try:
        order, created = await create_api_order(
            db, caller=caller, body=body, settings=get_settings()
        )
    except InsufficientBalanceError as exc:
        raise PaymentRequiredError(
            "the USD balance does not cover this order", code="insufficient_balance"
        ) from exc
    out = await get_for_owner(db, user_id, order.number)
    if out is None:  # pragma: no cover -- the owner's order, just read or written
        raise NotFoundError("no such order", code="order_not_found")
    if not created:
        raise ConflictError(
            "this client_order_id was already used",
            code="duplicate_client_order_id",
            order=out.model_dump(mode="json"),
        )
    return out


@router.get(
    "/orders/{order_id}",
    response_model=PublicOrderOut,
    summary="One API order of this account",
    responses={**_AUTH_ERRORS, 404: {"description": "`order_not_found`"}},
)
async def get_order(
    order_id: str,
    caller: Annotated[ApiCaller, Depends(api_caller)],
    db: Annotated[AsyncSession, Depends(db_session)],
) -> PublicOrderOut:
    """The API order ``order_id`` of this key's owner (any of their keys); another user's or
    an unknown one is 404."""
    await enforce(caller, "read")
    out = await get_for_owner(db, caller.user.id, order_id)
    if out is None:
        raise NotFoundError("no such order", code="order_not_found")
    return out


@router.get(
    "/orders",
    response_model=PublicOrdersPage,
    summary="API orders of this account",
    responses={**_AUTH_ERRORS, 422: {"description": "`cursor` or a bad `status`"}},
)
async def list_orders(
    caller: Annotated[ApiCaller, Depends(api_caller)],
    db: Annotated[AsyncSession, Depends(db_session)],
    cursor: Annotated[str | None, Query(max_length=256)] = None,
    status: PublicOrderStatus | None = None,
) -> PublicOrdersPage:
    """The owner's API orders (every key they had), newest first, 50 a page; ``status`` keeps
    one status."""
    await enforce(caller, "read")
    items, next_cursor = await list_for_owner(db, caller.user.id, cursor, status)
    return PublicOrdersPage(items=items, next_cursor=next_cursor)


@router.get("/me", response_model=MeOut, summary="Balance, key and limits", responses=_AUTH_ERRORS)
async def me(
    caller: Annotated[ApiCaller, Depends(api_caller)],
    db: Annotated[AsyncSession, Depends(db_session)],
) -> MeOut:
    """The USD balance, whether the USD wallet is on, the calling key and its limits."""
    await enforce(caller, "read")
    key = caller.key
    return MeOut(
        balance_usd=wire_usd(await user_usd_balance(db, caller.user.id)),
        usd_wallet_enabled=caller.user.usd_wallet_enabled,
        key=MeKeyOut(id=key.id, pricing_profile=key.pricing_profile, created_at=key.created_at),
        limits=MeLimitsOut(
            read_per_min=LIMITS["read"],
            orders_per_min=LIMITS["order"],
            feed_per_min=LIMITS["feed"],
        ),
    )


_WEBHOOK_SAVE_SCOPE = "public_api.webhook_put"
_WEBHOOK_DELETE_SCOPE = "public_api.webhook_delete"


@router.get(
    "/webhook",
    response_model=WebhookOut | None,
    summary="My webhook",
    responses=_AUTH_ERRORS,
)
async def get_webhook(
    caller: Annotated[ApiCaller, Depends(api_caller)],
    db: Annotated[AsyncSession, Depends(db_session)],
) -> WebhookOut | None:
    """The webhook URL and the state of its latest delivery, or ``null`` when none is set."""
    await enforce(caller, "read")
    return await webhooks.get(db, caller.user.id)


@router.put(
    "/webhook",
    response_model=WebhookOut,
    summary="Set my webhook URL",
    responses={
        **_AUTH_ERRORS,
        422: {"description": "`webhook_url_invalid`, `webhook_url_private`, `idempotency_key`"},
    },
)
async def put_webhook(
    body: WebhookIn,
    caller: Annotated[ApiCaller, Depends(api_caller)],
    db: Annotated[AsyncSession, Depends(db_session)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> WebhookOut:
    """Replace the webhook URL. ``https`` only; the host must resolve to public addresses.

    Needs ``Idempotency-Key``. A replay changes nothing and answers the current state.
    """
    idem = require_idempotency_key(idempotency_key)
    await enforce(caller, "read")
    # Check and resolve before any DB read, so no transaction is open across the lookup.
    url = check_url(body.url)
    parts = urlsplit(url)
    await public_addresses(parts.hostname or "", parts.port or 443)
    user_id = caller.user.id
    scoped = f"{user_id}:{idem}"
    request = {"url": url}
    hit = await load_replay(db, scope=_WEBHOOK_SAVE_SCOPE, idempotency_key=scoped)
    if hit is not None:
        stored = hit.body or {}
        if stored.get("request") != request:
            raise ConflictError(
                "this Idempotency-Key was used for another request", code="idempotency_mismatch"
            )
        return WebhookOut.model_validate(stored["response"])
    await webhooks.put(db, user_id, url)
    out = await webhooks.get(db, user_id)
    if out is None:  # pragma: no cover -- written one statement ago
        raise NotFoundError("no webhook is set", code="webhook_missing")
    await save_replay(
        db,
        scope=_WEBHOOK_SAVE_SCOPE,
        idempotency_key=scoped,
        body={"request": request, "response": out.model_dump(mode="json")},
        status_code=200,
    )
    await db.commit()
    return out


@router.delete(
    "/webhook",
    status_code=204,
    summary="Remove my webhook",
    responses={**_AUTH_ERRORS, 422: {"description": "`idempotency_key`"}},
)
async def delete_webhook(
    caller: Annotated[ApiCaller, Depends(api_caller)],
    db: Annotated[AsyncSession, Depends(db_session)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> Response:
    """Remove the webhook; 204 even when none was set. Needs ``Idempotency-Key``."""
    idem = require_idempotency_key(idempotency_key)
    await enforce(caller, "read")
    scoped = f"{caller.user.id}:{idem}"
    if await load_replay(db, scope=_WEBHOOK_DELETE_SCOPE, idempotency_key=scoped) is None:
        await webhooks.remove(db, caller.user.id)
        await save_replay(
            db, scope=_WEBHOOK_DELETE_SCOPE, idempotency_key=scoped, body=None, status_code=204
        )
        await db.commit()
    return Response(status_code=204)
