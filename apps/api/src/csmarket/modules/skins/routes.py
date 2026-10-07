"""Public ``/skins/*`` reads: catalogue, facets, suggest and the item page.

Prices are shown in soʻm at the CBU rate (``fx``); without a fresh rate the pages
show dollars and soʻm bounds are ignored (ruling Q3). No per-route rate bucket here:
these read only our own database. The live-listings proxy is the exception and
carries its own bucket. The sitemap slugs live in ``seo_routes``.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
from collections.abc import Awaitable, Callable
from decimal import Decimal
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Request
from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.api.v1.deps import db_session
from csmarket.core.clock import now
from csmarket.core.config import get_settings
from csmarket.core.errors import ValidationError
from csmarket.core.redis import get_redis
from csmarket.modules.auth.api import guard_ip
from csmarket.modules.fx.api import current_usd_uzs
from csmarket.modules.skins.cachekeys import catalog_version
from csmarket.modules.skins.images import steam_image, steam_image_only
from csmarket.modules.skins.listings import (
    Listing,
    SearchClient,
    listings_budget,
    listings_for,
    search_client,
    steam_inspect_url,
)
from csmarket.modules.skins.models import SkinItem
from csmarket.modules.skins.offers import from_listing, merge_offers, offer_id_of
from csmarket.modules.skins.pricing import (
    PricingRules,
    max_usd_for_uzs,
    min_usd_for_uzs,
    quote,
    to_uzs,
)
from csmarket.modules.skins.schemas import (
    FacetOut,
    RarityFacetOut,
    SkinDetailOut,
    SkinFacetsOut,
    SkinFamilyMemberOut,
    SkinItemOut,
    SkinListingOut,
    SkinListingsOut,
    SkinListingSummaryOut,
    SkinsPageOut,
    SkinStickerOut,
    SkinSuggestOut,
)
from csmarket.modules.skins.service import (
    CatalogQuery,
    Sort,
    facets,
    family,
    get_item,
    list_items,
    suggest,
)
from csmarket.modules.skins.settings import enabled_categories, load_rules
from csmarket.modules.skinslink.api import offers_for

_PAGE_TTL = 60

router = APIRouter(prefix="/skins", tags=["skins"])

#: A JSON-ready page body as cached in Redis.
# Any: the ``model_dump(mode="json")`` of one of this module's response models.
_Body = dict[str, Any]


async def usd_uzs_rate(db: AsyncSession) -> Decimal | None:
    """Soʻm per dollar for display, or ``None`` (pages then show dollars — ruling Q3)."""
    settings = get_settings()
    fx = await current_usd_uzs(db, get_redis(), max_age_days=settings.fx_max_age_days)
    return None if fx is None else fx.rate


def _to_uzs(usd: Decimal | None, rate: Decimal | None, rules: PricingRules) -> str | None:
    if usd is None or rate is None:
        return None
    return str(to_uzs(usd, rate, round_to=rules.uzs_round_to))


def _units_to_usd(units: int | None) -> str | None:
    return None if units is None else str(Decimal(units) / Decimal(1000))


def _item_out(item: SkinItem, rules: PricingRules, rate: Decimal | None) -> SkinItemOut:
    # Stored by ``repricing.reprice_rows`` from the same ``quote()``: the card
    # shows the number every filter and sort reads.
    price = item.sell_price_usd
    discount = (
        item.discount_percent if item.discount_percent and item.discount_percent > 0 else None
    )
    return SkinItemOut(
        slug=item.slug,
        name=item.market_hash_name,
        phase=item.phase or None,
        category=item.category,
        weapon=item.weapon,
        skin=item.skin,
        exterior=item.exterior,
        stattrak=item.stattrak,
        souvenir=item.souvenir,
        rarity=item.rarity,
        rarity_color=item.rarity_color,
        image_url=steam_image(item.image_url, host=get_settings().skins_image_host),
        price_usd=None if price is None else str(price),
        price_uzs=_to_uzs(price, rate, rules),
        steam_price_usd=_units_to_usd(item.steam_price_units),
        discount_percent=discount,
        count=item.count_auto + item.skinslink_count,
        min_float=None if item.min_float is None else str(item.min_float),
        max_float=None if item.max_float is None else str(item.max_float),
    )


# Any: query values of mixed types (str, bool, Decimal, None), digested via ``default=str``.
async def _cached(key_parts: dict[str, Any], build: Callable[[], Awaitable[_Body]]) -> _Body:
    """60 s Redis cache keyed by the catalogue version and a digest of the query.

    Every Redis error is swallowed: without Redis each request just builds its page.
    """
    redis = get_redis()
    version = await catalog_version(redis)
    # A cache key, not a secret: sha1 keeps arbitrary query text out of Redis keys.
    digest = hashlib.sha1(json.dumps(key_parts, sort_keys=True, default=str).encode()).hexdigest()  # noqa: S324
    key = f"skins:{key_parts['kind']}:{version}:{digest}"
    with contextlib.suppress(RedisError):
        cached = await redis.get(key)
        if cached is not None:
            loaded: _Body = json.loads(cached)
            return loaded
    value = await build()
    with contextlib.suppress(RedisError):
        await redis.set(key, json.dumps(value), ex=_PAGE_TTL)
    return value


@router.get("/catalog", response_model=SkinsPageOut, summary="Browse the skins catalogue")
async def get_catalog(
    *,
    db: Annotated[AsyncSession, Depends(db_session)],
    category: str | None = None,
    weapon: str | None = None,
    exterior: str | None = None,
    stattrak: bool | None = None,
    souvenir: bool | None = None,
    rarity: Annotated[str | None, Query(max_length=64)] = None,
    team: Annotated[Literal["ct", "t"] | None, Query()] = None,
    min_uzs: Annotated[Decimal | None, Query(ge=0, le=10**12)] = None,
    max_uzs: Annotated[Decimal | None, Query(ge=0, le=10**12)] = None,
    q: Annotated[str | None, Query(max_length=80)] = None,
    sort: Sort = "-price",
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 48,
) -> SkinsPageOut:
    """One page of on-sale items, dearest first by default; ``q`` ranks by match."""
    rate = await usd_uzs_rate(db)
    # Bounds arrive in soʻm (what the customer typed) and compare with our USD sell
    # price, turned into the cents whose rounded-up card is inside them (a card at
    # exactly the bound is kept). Without a rate the bounds are dropped, not guessed.
    min_usd = max_usd = None
    if rate is not None and (min_uzs is not None or max_uzs is not None):
        round_to = (await load_rules(db)).uzs_round_to
        if min_uzs is not None:
            min_usd = min_usd_for_uzs(min_uzs, rate, round_to=round_to)
        if max_uzs is not None:
            max_usd = max_usd_for_uzs(max_uzs, rate, round_to=round_to)
    query = CatalogQuery(
        category=category,
        weapon=weapon,
        exterior=exterior,
        stattrak=stattrak,
        souvenir=souvenir,
        rarity=rarity,
        team=team,
        min_usd=min_usd,
        max_usd=max_usd,
        q=q,
        sort=sort,
        cursor=cursor,
        limit=limit,
    )
    categories = enabled_categories(get_settings())

    async def build() -> _Body:
        rules = await load_rules(db)
        items, next_cursor = await list_items(db, query, categories=categories)
        return SkinsPageOut(
            items=[_item_out(i, rules, rate) for i in items], next_cursor=next_cursor
        ).model_dump(mode="json")

    # The rate is part of the key: a new rate must not serve soʻm from the old one.
    parts = {"kind": "catalog", "rate": rate, **query.__dict__}
    return SkinsPageOut.model_validate(await _cached(parts, build))


@router.get("/facets", response_model=SkinFacetsOut, summary="Counts per category, weapon, wear")
async def get_facets(
    db: Annotated[AsyncSession, Depends(db_session)],
    category: Annotated[str | None, Query(max_length=32)] = None,
) -> SkinFacetsOut:
    """Facet counts; with ``category`` the weapon, wear and rarity facets are scoped to it."""
    categories = enabled_categories(get_settings())
    if category is not None and category not in categories:
        raise ValidationError(f"unknown skins category: {category}")

    async def build() -> _Body:
        f = await facets(db, categories=categories, category=category)
        return SkinFacetsOut(
            categories=[FacetOut(value=v, count=c) for v, c in f.categories],
            weapons=[FacetOut(value=v, count=c) for v, c in f.weapons],
            exteriors=[FacetOut(value=v, count=c) for v, c in f.exteriors],
            rarities=[RarityFacetOut(value=v, count=c, color=k) for v, c, k in f.rarities],
            teams=[FacetOut(value=v, count=c) for v, c in f.teams],
        ).model_dump(mode="json")

    return SkinFacetsOut.model_validate(
        await _cached({"kind": "facets", "category": category}, build)
    )


@router.get("/suggest", response_model=SkinSuggestOut, summary="Search-as-you-type")
async def get_suggest(
    db: Annotated[AsyncSession, Depends(db_session)],
    q: Annotated[str, Query(min_length=1, max_length=80)],
) -> SkinSuggestOut:
    """Up to ten on-sale items matching ``q`` (aliases expanded), best match first."""
    categories = enabled_categories(get_settings())
    rate = await usd_uzs_rate(db)

    async def build() -> _Body:
        rules = await load_rules(db)
        items = await suggest(db, q, categories=categories)
        return SkinSuggestOut(items=[_item_out(i, rules, rate) for i in items]).model_dump(
            mode="json"
        )

    parts = {"kind": "suggest", "q": q.lower(), "rate": rate}
    return SkinSuggestOut.model_validate(await _cached(parts, build))


@router.get("/{slug}", response_model=SkinDetailOut, summary="One item with its cheapest listings")
async def get_detail(slug: str, db: Annotated[AsyncSession, Depends(db_session)]) -> SkinDetailOut:
    """The item page; a sold-out item is a page, an unknown or hidden one a 404."""
    categories = enabled_categories(get_settings())
    item = await get_item(db, slug, categories=categories)
    rules = await load_rules(db)
    rate = await usd_uzs_rate(db)
    base = _item_out(item, rules, rate)
    cheapest: list[SkinListingSummaryOut] = []
    for entry in item.cheapest_auto:
        usd = quote(
            int(entry["price_units"]),
            rules=rules,
            category=item.category,
            weapon=item.weapon,
            count_auto=item.count_auto + item.skinslink_count,
            item_pp=item.margin_override_pp,
            fixed_price_usd=item.fixed_price_usd,
            steam_price_units=item.steam_price_units,
        ).price_usd
        cheapest.append(
            SkinListingSummaryOut(
                listing_id=offer_id_of("waxpeer", int(entry["listing_id"])),
                price_usd=str(usd),
                price_uzs=_to_uzs(usd, rate, rules),
            )
        )
    members = [
        SkinFamilyMemberOut(
            slug=m.slug,
            exterior=m.exterior,
            stattrak=m.stattrak,
            souvenir=m.souvenir,
            price_usd=None if m.sell_price_usd is None else str(m.sell_price_usd),
            price_uzs=_to_uzs(m.sell_price_usd, rate, rules),
            count=m.count_auto + m.skinslink_count,
        )
        for m in await family(db, item, categories=categories)
    ]
    return SkinDetailOut(
        **base.model_dump(),
        cheapest=cheapest,
        family=members,
        buy_enabled=get_settings().skins_buy_enabled,
    )


@router.get(
    "/{slug}/listings",
    response_model=SkinListingsOut,
    summary="Live auto listings for one item (cached, rate-budgeted, degradable)",
)
async def get_listings(
    slug: str,
    request: Request,
    db: Annotated[AsyncSession, Depends(db_session)],
    client: Annotated[SearchClient, Depends(search_client)],
) -> SkinListingsOut:
    """Live offers for one item; a Waxpeer problem is a 200 with ``degraded: true``.

    Advisory read, so no ``Idempotency-Key``. An unknown or hidden slug is a 404 before
    any Waxpeer call.
    """
    # Spends Waxpeer quota on a cache miss — the bucket bounds distinct items per address.
    await guard_ip(request, bucket="skins-listings")
    settings = get_settings()
    item = await get_item(db, slug, categories=enabled_categories(settings))
    rules = await load_rules(db)
    rate = await usd_uzs_rate(db)
    # Skinslink's offers come from our mirror (a DB read, no external call); this route
    # composes the two sources — ``skins`` itself never imports ``skinslink``.
    extra = await offers_for(db, item.id, settings=settings, now=now())
    rows: list[Listing] = []
    degraded = False
    if settings.waxpeer_buy_enabled:  # off: Skinslink resells the same listings, cheaper
        rows, degraded = await listings_for(
            item, client=client, redis=get_redis(), budget_per_minute=listings_budget(settings)
        )
    items: list[SkinListingOut] = []
    for row in merge_offers([from_listing(r) for r in rows], extra):
        usd = quote(
            row.price_units,
            rules=rules,
            category=item.category,
            weapon=item.weapon,
            count_auto=item.count_auto + item.skinslink_count,
            item_pp=item.margin_override_pp,
            fixed_price_usd=item.fixed_price_usd,
            steam_price_units=item.steam_price_units,
        ).price_usd
        items.append(
            SkinListingOut(
                listing_id=row.offer_id,
                price_usd=str(usd),
                price_uzs=_to_uzs(usd, rate, rules),
                float_value=row.float_value,
                paint_seed=row.paint_seed,
                stickers=[
                    SkinStickerOut.model_validate(
                        {
                            **s,
                            "image": steam_image_only(
                                s.get("image"), host=settings.skins_image_host
                            ),
                        }
                    )
                    for s in row.stickers
                ],
                # Checked again on the way out: a cached entry may predate the parse rule.
                inspect_url=steam_inspect_url(row.inspect_url),
            )
        )
    return SkinListingsOut(items=items, degraded=degraded)


__all__ = ["router", "usd_uzs_rate"]
