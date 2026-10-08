"""Buying over the public API: ``POST /public/orders`` (spec 2026-10-09 §5, plan B Task 5).

One transaction: resolve the offer from our own tables (Skinslink and LIS-SKINS, priced by
the key's tariff — no market is called), insert the order, debit the USD wallet and mark it
``paid`` (NOTIFY the worker). There is no pending stage: the caller already holds the money
with us. A short balance rolls everything back (no order, no posting).

A repeated ``client_order_id`` returns the order already placed under it. Two requests racing
with the same one meet at the unique ``(api_key_id, client_order_id)``: the loser's insert waits
for the winner's commit, fails, rolls back to its savepoint and reads the winner. Its debit key
is the order id, so a rolled-back loser has debited nothing.

Ruling R1: the order stores ``price_uzs = 0``, the newest rate snapshot (any age) and
``fx_uplift_pct = 0``; ``price_usd`` is the charged price. The trade link is PII: never logged.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.clock import now
from csmarket.core.config import Settings
from csmarket.core.errors import ConflictError, ForbiddenError, NotFoundError
from csmarket.core.logging import get_logger
from csmarket.core.money import wire_usd
from csmarket.core.numbers import allocate, order_number
from csmarket.modules.fx.api import FxSnapshot
from csmarket.modules.orders.checkout import RateUnavailableError, _float_of
from csmarket.modules.orders.models import Order
from csmarket.modules.orders.paid import mark_paid
from csmarket.modules.public_api.api import (
    ApiCaller,
    ApiOrderIn,
    PricedOffer,
    api_offers,
    open_offer_id,
)
from csmarket.modules.skins.api import SkinItem, enabled_categories, get_item_by_id
from csmarket.modules.users.api import parse_tradelink
from csmarket.modules.wallet.api import USD_WALLET, InsufficientBalanceError, debit_purchase_usd

log = get_logger("csmarket.orders.api_checkout")

_UNITS_PER_USD = Decimal(1000)
_USD_PLACES = Decimal("0.000001")


async def _by_client_id(db: AsyncSession, key_id: str, client_order_id: str) -> Order | None:
    """The order placed under ``client_order_id`` with key ``key_id``, if any."""
    return await db.scalar(
        select(Order).where(Order.api_key_id == key_id, Order.client_order_id == client_order_id)
    )


def _usd(units: int) -> Decimal:
    """Milli-USD ``units`` as dollars, as ``orders`` stores them (six places)."""
    return (Decimal(units) / _UNITS_PER_USD).quantize(_USD_PLACES)


def _above_max(price_units: int) -> ConflictError:
    return ConflictError(
        "the price is above max_price_usd", code="price_above_max", price_usd=wire_usd(price_units)
    )


def _offer_gone() -> ConflictError:
    return ConflictError("this offer is no longer available", code="offer_gone")


def choose(priced: list[PricedOffer], body: ApiOrderIn, item_id: str) -> PricedOffer:
    """The offer to buy: the one named by ``offer_id``, else the cheapest within the cap.

    Args:
        priced: The item's offers, cheapest first, priced for the key's tariff.
        body: The request (``offer_id``, ``max_price_usd``).
        item_id: The item the opaque ``offer_id`` must be bound to.

    Raises:
        ConflictError: ``offer_gone`` — a forged, foreign or sold offer id, or no offers;
            ``price_above_max`` (with ``price_usd``) — the offer costs more than the cap.
    """
    cap = int(Decimal(body.max_price_usd) * _UNITS_PER_USD)
    if body.offer_id is not None:
        internal = open_offer_id(body.offer_id, item_id)
        chosen = next((p for p in priced if internal and p.offer.offer_id == internal), None)
        if chosen is None:
            raise _offer_gone()
        if chosen.price_units > cap:
            raise _above_max(chosen.price_units)
        return chosen
    if not priced:
        raise _offer_gone()
    cheapest = next((p for p in priced if p.price_units <= cap), None)
    if cheapest is None:
        raise _above_max(priced[0].price_units)
    return cheapest


def _gate(caller: ApiCaller, body: ApiOrderIn, settings: Settings) -> str:
    """The parsed trade link, once buying and the caller's USD wallet are on.

    Raises:
        ConflictError: ``buying_disabled``.
        ForbiddenError: ``usd_wallet_disabled``.
        ValidationError: ``trade_link_invalid`` (422).
    """
    if not settings.skins_buy_enabled:
        raise ConflictError("buying is switched off", code="buying_disabled")
    if not caller.user.usd_wallet_enabled:
        raise ForbiddenError("the dollar wallet is not enabled", code="usd_wallet_disabled")
    return parse_tradelink(body.trade_link).url


async def _newest_snapshot_id(db: AsyncSession) -> str:
    """The newest rate snapshot, whatever its age (ruling R1).

    Raises:
        RateUnavailableError: no snapshot was ever recorded (503 ``rate_unavailable``).
    """
    found = await db.scalar(select(FxSnapshot.id).order_by(FxSnapshot.fetched_at.desc()).limit(1))
    if found is None:
        raise RateUnavailableError("no rate snapshot", code="rate_unavailable")
    return found


def _build(
    caller: ApiCaller,
    body: ApiOrderIn,
    item: SkinItem,
    chosen: PricedOffer,
    *,
    link: str,
    snapshot_id: str,
    settings: Settings,
) -> Order:
    offer = chosen.offer
    return Order(
        user_id=caller.user.id,
        status="pending",
        channel="api",
        api_key_id=caller.key.id,
        client_order_id=body.client_order_id,
        pricing_profile=caller.key.pricing_profile,
        skin_item_id=item.id,
        market_hash_name=item.market_hash_name,
        phase=item.phase,
        slug=item.slug,
        source=offer.source,
        offer_id=offer.offer_id,
        listing_id=None,
        float_value=_float_of(offer.float_value),
        paint_seed=offer.paint_seed,
        cost_units=offer.price_units,
        cost_usd=_usd(offer.price_units),
        price_usd=_usd(chosen.price_units),
        price_uzs=Decimal(0),
        fx_snapshot_id=snapshot_id,
        fx_uplift_pct=Decimal(0),
        trade_link=link,
        idempotency_key=f"api:{caller.key.id}:{body.client_order_id}",
        expires_at=now() + timedelta(minutes=settings.order_expiry_minutes),
    )


async def create_api_order(
    db: AsyncSession, *, caller: ApiCaller, body: ApiOrderIn, settings: Settings
) -> tuple[Order, bool]:
    """Buy one offer for the caller from their USD wallet; the order is ``paid`` on return.

    Args:
        db: The request's session; committed on success, rolled back on a short balance.
        caller: The key and its owner.
        body: The request.
        settings: Settings (the buying switch, the sources, the order expiry).

    Returns:
        ``(order, created)`` — ``created`` is ``False`` when the key already placed an order
        under ``client_order_id`` (that order is returned, nothing is written).

    Raises:
        ConflictError: ``buying_disabled``, ``offer_gone``, ``price_above_max``.
        ForbiddenError: ``usd_wallet_disabled``.
        ValidationError: ``trade_link_invalid``.
        NotFoundError: ``item_not_found`` — unknown, inactive, hidden or disabled category.
        InsufficientBalanceError: the USD balance does not cover the price; nothing written.
        RateUnavailableError: no rate snapshot at all.
    """
    key_id, user_id = caller.key.id, caller.user.id
    existing = await _by_client_id(db, key_id, body.client_order_id)
    if existing is not None:
        return existing, False
    link = _gate(caller, body, settings)
    item = await get_item_by_id(db, body.item_id, categories=enabled_categories(settings))
    if item is None:
        raise NotFoundError("no such item", code="item_not_found")
    priced = await api_offers(
        db, item, profile=caller.key.pricing_profile, settings=settings, now=now()
    )
    chosen = choose(priced, body, item.id)
    snapshot_id = await _newest_snapshot_id(db)
    order = _build(
        caller, body, item, chosen, link=link, snapshot_id=snapshot_id, settings=settings
    )
    order.number = await allocate(db, Order.number, order_number)
    try:
        async with db.begin_nested():
            db.add(order)
            await db.flush()
    except IntegrityError:  # the same client_order_id raced us: the winner's order stands
        winner = await _by_client_id(db, key_id, body.client_order_id)
        if winner is None:
            raise
        return winner, False
    try:
        await debit_purchase_usd(
            db, user_id=user_id, order_id=order.id, units=Decimal(chosen.price_units)
        )
    except InsufficientBalanceError:
        await db.rollback()  # no order, no posting
        raise
    await mark_paid(db, order, provider=USD_WALLET)
    await db.commit()
    log.info(
        "orders.api_created",
        number=order.number,
        key_id=key_id,
        source=order.source,
        price_units=chosen.price_units,
    )
    return order, True


__all__ = ["choose", "create_api_order"]
