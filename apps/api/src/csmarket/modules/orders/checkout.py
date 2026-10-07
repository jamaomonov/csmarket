"""Checkout: ``POST /orders`` re-prices the chosen offer from the live listings (spec §7.4).

The price the buyer was shown is a courtesy check within ±``order_price_tolerance``; the
server's number is what is billed. A chosen offer that is gone is never replaced — another lot
has its own float, pattern and stickers: 409 ``offer_gone`` with the cheapest offer left, and
the buyer decides (ADR-0013).

The order snapshots everything buying needs: the offer and its cost in Waxpeer units (the
worker's price cap), the price in soʻm and dollars, the rate it was priced at, and the
buyer's trade link (PII: never logged).

No database connection is held across the listings read: the scalars it needs are copied
into a frozen value object and the read transaction ends first (AGENTS §11). The listings
read is the cached, budgeted, degradable one the item page uses (ruling R11); a degraded
answer is accepted — the worker's price cap is the money guard. A chosen LIS-SKINS lot is
re-checked live (``lisskins.recheck_chosen``, one call, 4 s, budgeted, breaker-guarded): sold →
``offer_gone``; no answer → the snapshot price.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal
from typing import Any

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.clock import now
from csmarket.core.config import Settings
from csmarket.core.errors import ConflictError, UpstreamUnavailableError, ValidationError
from csmarket.core.logging import get_logger
from csmarket.core.numbers import allocate, order_number
from csmarket.modules.fx.api import UsdUzs, current_usd_uzs
from csmarket.modules.lisskins.api import AvailabilityClient, recheck_chosen
from csmarket.modules.lisskins.api import offers_for as lisskins_offers
from csmarket.modules.orders.models import Order
from csmarket.modules.orders.schemas import OrderCreateIn
from csmarket.modules.skins.api import (
    TIE_ORDER,
    Listing,
    Offer,
    PricingRules,
    SearchClient,
    SkinItem,
    enabled_categories,
    from_listing,
    get_item,
    listings_budget,
    listings_for,
    load_rules,
    merge_offers,
    quote,
    to_uzs,
)
from csmarket.modules.skinslink.api import offers_for as skinslink_offers
from csmarket.modules.users.api import User, parse_tradelink

log = get_logger("csmarket.orders.checkout")

_USD_PLACES = Decimal("0.000001")
_UNITS_PER_USD = Decimal(1000)
#: Stored verdicts that refuse a link. ``warn`` is the pre-2026-10-01 verdict of a trade
#: hold, which is refused now (owner decision D2); a stored or cached one still refuses.
_BAD_VERDICTS = frozenset({"bad", "warn"})

#: ``(offer, (price_usd, price_uzs))`` — one live offer priced for the buyer.
_Priced = tuple[Offer, tuple[Decimal, Decimal]]


class RateUnavailableError(UpstreamUnavailableError):
    """No fresh soʻm rate: nothing can be priced in soʻm right now."""

    status_code = 503
    type_uri = "https://csmarket.uz/errors/rate-unavailable"
    title = "Rate unavailable"


@dataclass(frozen=True)
class _ItemSnapshot:
    """What checkout needs of the item once the read transaction is over."""

    id: str
    slug: str
    market_hash_name: str
    phase: str
    category: str
    weapon: str | None
    count_auto: int
    margin_override_pp: Decimal | None
    fixed_price_usd: Decimal | None
    steam_price_units: int | None
    # Any: the snapshot's ``cheapest_auto`` JSON entries as stored.
    cheapest_auto: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def of(cls, item: SkinItem) -> _ItemSnapshot:
        """Copy the scalars of a loaded ``item``."""
        return cls(
            id=item.id,
            slug=item.slug,
            market_hash_name=item.market_hash_name,
            phase=item.phase,
            category=item.category,
            weapon=item.weapon,
            # Both sources' stock, as the catalogue prices it (``skins.repricing``).
            count_auto=item.stock_count,  # every source's stock, as the catalogue prices it
            margin_override_pp=item.margin_override_pp,
            fixed_price_usd=item.fixed_price_usd,
            steam_price_units=item.steam_price_units,
            cheapest_auto=list(item.cheapest_auto),
        )

    def item_view(self) -> SkinItem:
        """A transient (never added to a session) item for ``listings_for``."""
        return SkinItem(
            id=self.id,
            slug=self.slug,
            market_hash_name=self.market_hash_name,
            phase=self.phase,
            cheapest_auto=self.cheapest_auto,
        )


def _price(
    units: int, snap: _ItemSnapshot, rules: PricingRules, rate: Decimal
) -> tuple[Decimal, Decimal]:
    """``(price_usd, price_uzs)`` of an offer costing ``units`` — the item page's numbers."""
    usd = quote(
        units,
        rules=rules,
        category=snap.category,
        weapon=snap.weapon,
        count_auto=snap.count_auto,
        item_pp=snap.margin_override_pp,
        fixed_price_usd=snap.fixed_price_usd,
        steam_price_units=snap.steam_price_units,
    ).price_usd
    return usd, to_uzs(usd, rate, round_to=rules.uzs_round_to)


def _choose(
    priced: list[_Priced], body: OrderCreateIn, settings: Settings
) -> tuple[Offer, Decimal, Decimal]:
    """``(offer, price_usd, price_uzs)`` to bill, or a 409 — the ±2 % rule; a gone offer is
    never replaced (ADR-0013).

    Raises:
        ConflictError: ``price_changed`` (with the new ``price_uzs``) or ``offer_gone``
            (with ``next_offer``, ``None`` when nothing is listed).
    """
    shown = Decimal(body.price_uzs)
    chosen = next((p for p in priced if p[0].offer_id == body.listing_id), None)
    if chosen is not None:
        row, (usd, uzs) = chosen
        if abs(uzs - shown) > shown * settings.order_price_tolerance:
            raise ConflictError("the price has changed", code="price_changed", price_uzs=str(uzs))
        return row, usd, uzs
    cheapest = min(
        priced,
        # Waxpeer, Skinslink, LIS-SKINS on a tie.
        key=lambda p: (p[1][1], TIE_ORDER[p[0].source], p[0].offer_id),
        default=None,
    )
    raise ConflictError(
        "this offer was just sold",
        code="offer_gone",
        next_offer=None
        if cheapest is None
        else {"listing_id": cheapest[0].offer_id, "price_uzs": str(cheapest[1][1])},
    )


def _gate_trade_link(user: User) -> str:
    """The buyer's saved trade link, if it may receive the skin (ruling R10).

    An unchecked link and one whose check was ``unavailable`` pass: the check is advisory.

    Raises:
        ConflictError: ``trade_link_missing``; ``trade_link_bad`` with ``reason``.
    """
    if not user.trade_link:
        raise ConflictError("add your Steam trade link first", code="trade_link_missing")
    if user.trade_link_verdict in _BAD_VERDICTS:
        reason = user.trade_link_reason or ("hold" if user.trade_link_verdict == "warn" else None)
        raise ConflictError(
            "this trade link cannot receive skins",
            code="trade_link_bad",
            reason=reason or "invalid",
        )
    try:
        return parse_tradelink(user.trade_link).url
    except ValidationError as exc:
        raise ConflictError(
            "this trade link cannot receive skins", code="trade_link_bad", reason="invalid"
        ) from exc


async def _by_key(db: AsyncSession, user_id: str, key: str) -> Order | None:
    return await db.scalar(
        select(Order).where(Order.user_id == user_id, Order.idempotency_key == key)
    )


@dataclass(frozen=True)
class _Quoted:
    """Everything the order row needs once the read transaction is over."""

    user_id: str
    trade_link: str
    snap: _ItemSnapshot
    rules: PricingRules
    rate: UsdUzs
    #: Skinslink's and LIS-SKINS' offers, read inside the read transaction.
    extra: list[Offer]


async def _read(
    db: AsyncSession, redis: Redis, user: User, body: OrderCreateIn, settings: Settings
) -> _Quoted:
    """The gate and every database read checkout needs, copied out of the session."""
    if not settings.skins_buy_enabled:
        raise ConflictError("buying is switched off", code="buying_disabled")
    link = _gate_trade_link(user)
    item = await get_item(db, body.slug, categories=enabled_categories(settings))
    rules = await load_rules(db)
    rate = await current_usd_uzs(db, redis, max_age_days=settings.fx_max_age_days)
    if rate is None:
        raise RateUnavailableError("no soʻm rate", code="rate_unavailable")
    at = now()
    extra = [
        *await skinslink_offers(db, item.id, settings=settings, now=at),
        *await lisskins_offers(db, item.id, settings=settings, now=at),
    ]
    return _Quoted(
        user_id=user.id,
        trade_link=link,
        snap=_ItemSnapshot.of(item),
        rules=rules,
        rate=rate,
        extra=extra,
    )


def _build(
    q: _Quoted, row: Offer, usd: Decimal, uzs: Decimal, *, key: str, settings: Settings
) -> Order:
    return Order(
        user_id=q.user_id,
        status="pending",
        skin_item_id=q.snap.id,
        market_hash_name=q.snap.market_hash_name,
        phase=q.snap.phase,
        slug=q.snap.slug,
        source=row.source,
        offer_id=row.offer_id,
        listing_id=row.listing_id,
        cost_units=row.price_units,
        cost_usd=(Decimal(row.price_units) / _UNITS_PER_USD).quantize(_USD_PLACES),
        price_usd=usd,
        price_uzs=uzs,
        fx_snapshot_id=q.rate.snapshot_id,
        fx_uplift_pct=q.rate.uplift_pct,
        trade_link=q.trade_link,
        idempotency_key=key,
        expires_at=now() + timedelta(minutes=settings.order_expiry_minutes),
    )


async def create_order(
    db: AsyncSession,
    *,
    redis: Redis,
    user: User,
    body: OrderCreateIn,
    idempotency_key: str,
    client: SearchClient,
    settings: Settings,
    availability: AvailabilityClient | None = None,
) -> tuple[Order, bool]:
    """Open an order for one skin at the price the buyer saw (within the rules).

    Args:
        db: The request's session; committed on success.
        redis: For the listings cache, budget and breaker, and the rate copy.
        user: The signed-in buyer.
        body: The offer and the price the panel showed.
        idempotency_key: The request's key; a replay returns the stored order whatever
            ``body`` says.
        client: The Waxpeer listings client.
        settings: Settings (tolerance, expiry, the buying switch).
        availability: LIS-SKINS, for the chosen ``ls:`` lot's live price (ADR-0012); ``None``
            checks nothing.

    Returns:
        ``(order, created)`` — ``created`` is ``False`` for a replayed key.

    Raises:
        ConflictError: ``buying_disabled``, ``trade_link_missing``, ``trade_link_bad``,
            ``price_changed`` or ``offer_gone``.
        NotFoundError: Unknown, hidden or disabled-category item.
        RateUnavailableError: No fresh soʻm rate (503 ``rate_unavailable``).
    """
    existing = await _by_key(db, user.id, idempotency_key)
    if existing is not None:
        return existing, False
    q = await _read(db, redis, user, body, settings)
    await db.rollback()  # release the connection before the listings read
    rows: list[Listing] = []
    degraded = False
    if settings.waxpeer_buy_enabled:  # off: Skinslink's offers only
        rows, degraded = await listings_for(
            q.snap.item_view(),
            client=client,
            redis=redis,
            budget_per_minute=listings_budget(settings),
        )
    offers = merge_offers([from_listing(r) for r in rows], q.extra)
    if availability is not None:  # one call, only for a chosen LIS-SKINS lot; no session held
        offers = await recheck_chosen(
            offers, str(body.listing_id), redis=redis, client=availability
        )
    priced = [(o, _price(o.price_units, q.snap, q.rules, q.rate.rate)) for o in offers]
    row, usd, uzs = _choose(priced, body, settings)
    order = _build(q, row, usd, uzs, key=idempotency_key, settings=settings)
    order.number = await allocate(db, Order.number, order_number)
    db.add(order)
    try:
        await db.flush()
    except IntegrityError:  # the same key raced us: the other request's order stands
        await db.rollback()
        replay = await _by_key(db, q.user_id, idempotency_key)
        if replay is None:
            raise
        return replay, False
    await db.commit()
    log.info(
        "orders.created",
        number=order.number,
        price_uzs=str(uzs),
        source=row.source,
        degraded=degraded,
    )
    return order, True


__all__ = ["RateUnavailableError", "create_order"]
