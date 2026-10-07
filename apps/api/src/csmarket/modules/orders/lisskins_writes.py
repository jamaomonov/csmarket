"""The LIS-SKINS buy's writes (``orders.lisskins_buying``): lock the order, then its purchase
(ruling K), re-check ``status == "buying"`` and ``buy_pending``, write, commit — and write
nothing when a sweep moved the rows during the LIS-SKINS call. Each returns the outcome.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.clock import now
from csmarket.core.logging import get_logger
from csmarket.core.metrics import TradeAttentionReason
from csmarket.modules.lisskins.api import LisskinsPurchase, Purchase
from csmarket.modules.orders.lisskins_status import apply_report
from csmarket.modules.orders.models import Order
from csmarket.modules.orders.refunds import refund_to_balance
from csmarket.modules.orders.substitutes import switch_source
from csmarket.modules.orders.trades import flag
from csmarket.modules.skins.api import Offer, parse_offer_id

log = get_logger("csmarket.orders.lisskins_buying")

_ACTOR = "orders"
#: Refund reason → outcome.
_REFUND_OUTCOMES: dict[str, str] = {
    "invalid_trade_link": "invalid_link",
    "sold_out": "sold_out",
    "source_low_balance": "low_balance",
}


class LisskinsSnapshot(BaseModel):
    """What a LIS-SKINS buy needs of the order, read unlocked before LIS-SKINS is called."""

    model_config = ConfigDict(frozen=True)

    order_id: str
    number: str
    skin_item_id: str
    custom_id: str
    skin_id: int
    paid_units: int
    #: The order's agreed cost: the substitute ceiling is counted from it.
    cost_units: int
    #: A repeat of a buy whose answer was lost: the first send may own the lot.
    repeat: bool = False


async def _lock_both(
    db: AsyncSession, order_id: str
) -> tuple[Order | None, LisskinsPurchase | None]:
    order = await db.scalar(
        select(Order)
        .where(Order.id == order_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    purchase = await db.scalar(
        select(LisskinsPurchase)
        .where(LisskinsPurchase.order_id == order_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return order, purchase


async def _locked(
    db: AsyncSession, snap: LisskinsSnapshot
) -> tuple[Order, LisskinsPurchase] | None:
    """Both rows ``FOR UPDATE`` if still ``buying`` with the buy pending; else ``None``."""
    order, purchase = await _lock_both(db, snap.order_id)
    if order is None or purchase is None or order.status != "buying" or not purchase.buy_pending:
        await db.commit()  # nothing written: just let the locks go
        return None
    return order, purchase


def _stale(snap: LisskinsSnapshot, outcome: str) -> str:
    """Someone moved the rows during the call, and nothing was bought: write nothing."""
    log.warning("orders.lisskins_buy.stale", number=snap.number, outcome=outcome)
    return "nothing_to_do"


async def _stale_purchase(db: AsyncSession, snap: LisskinsSnapshot) -> str:
    """A purchase that may have gone through landed on moved rows: flagged, never silent."""
    order, purchase = await _lock_both(db, snap.order_id)
    if order is not None and purchase is not None:
        flag(purchase, "ambiguous_trade", reopen=True)
    await db.commit()
    log.error("orders.lisskins_buy.stale_purchase", number=snap.number)
    return "stale_bought"


def _settle(purchase: LisskinsPurchase) -> None:
    """The buy is no longer pending; a ``source_forbidden`` attention is moot now."""
    purchase.buy_pending = False
    if purchase.attention_reason == "source_forbidden":
        purchase.attention_reason = None
        purchase.resolved_at = purchase.resolved_by = purchase.resolved_note = None
    purchase.updated_at = now()


async def record_purchase(
    db: AsyncSession, snap: LisskinsSnapshot, report: Purchase, *, outcome: str = "bought"
) -> str:
    """LIS-SKINS took the purchase (or ``market/info`` named it): record it, apply its status."""
    pair = await _locked(db, snap)
    if pair is None:
        return await _stale_purchase(db, snap)
    order, purchase = pair
    _settle(purchase)
    purchase.buy_unconfirmed_at = None
    await apply_report(db, order=order, purchase=purchase, report=report)
    await db.commit()
    return outcome


async def retarget(db: AsyncSession, snap: LisskinsSnapshot, offer: Offer) -> LisskinsSnapshot:
    """Point the purchase at a LIS-SKINS substitute under ``<order id>:2``, committed before
    the request goes out — a lost answer is then settled under the id actually used.

    Raises:
        LookupError: The order left ``buying`` meanwhile.
    """
    pair = await _locked(db, snap)
    if pair is None:
        raise LookupError("the order left buying")
    _, purchase = pair
    key, skin_id = f"{snap.order_id}:2", int(parse_offer_id(offer.offer_id)[1])
    purchase.custom_id, purchase.skin_id, purchase.paid_units = key, skin_id, offer.price_units
    purchase.updated_at = now()
    await db.commit()
    return snap.model_copy(
        update={"custom_id": key, "skin_id": skin_id, "paid_units": offer.price_units}
    )


async def switch(db: AsyncSession, snap: LisskinsSnapshot, offer: Offer) -> str:
    """A substitute of another source: that source's path buys it next; this row goes."""
    pair = await _locked(db, snap)
    if pair is None or (offer.source == "waxpeer" and offer.listing_id is None):
        return _stale(snap, "lookup_later")
    await switch_source(db, pair[0], offer)
    await db.commit()
    log.info("orders.lisskins_buy.switched", number=snap.number, source=offer.source)
    return "lookup_later"


async def unconfirmed(db: AsyncSession, snap: LisskinsSnapshot) -> str:
    """The answer was lost: the reconcile settles it by ``market/info`` (never a blind rebuy)."""
    pair = await _locked(db, snap)
    if pair is None:
        return await _stale_purchase(db, snap)
    _, purchase = pair
    _settle(purchase)
    purchase.buy_unconfirmed_at = now()
    await db.commit()
    return "unconfirmed"


async def held(db: AsyncSession, snap: LisskinsSnapshot) -> str:
    """A repeat that LIS-SKINS refused and ``market/info`` cannot explain: the first send may
    have bought the lot, so neither a refund nor another buy — the ``buy_unconfirmed``
    attention, and the purchase stays unconfirmed until an admin retries or settles it."""
    pair = await _locked(db, snap)
    if pair is None:
        return await _stale_purchase(db, snap)
    _, purchase = pair
    _settle(purchase)
    purchase.buy_unconfirmed_at = now()
    flag(purchase, "buy_unconfirmed", reopen=True)
    await db.commit()
    log.error("orders.lisskins_buy.repeat_refused", number=snap.number)
    return "unconfirmed"


async def secure_sent(db: AsyncSession, snap: LisskinsSnapshot) -> bool:
    """A buy this attempt sent but could not record: never leave it ``buy_pending``."""
    order, purchase = await _lock_both(db, snap.order_id)
    marked = order is not None and purchase is not None and purchase.buy_pending
    if marked and order is not None and purchase is not None:
        _settle(purchase)
        purchase.buy_unconfirmed_at = now()
        if order.status != "buying":
            flag(purchase, "ambiguous_trade", reopen=True)
    await db.commit()
    return marked


async def attention(
    db: AsyncSession, snap: LisskinsSnapshot, reason: TradeAttentionReason, *, outcome: str
) -> str:
    """Flag the purchase for an admin; the buy stays pending."""
    pair = await _locked(db, snap)
    if pair is None:
        return _stale(snap, outcome)
    flag(pair[1], reason, reopen=True)
    await db.commit()
    return outcome


async def refund(db: AsyncSession, snap: LisskinsSnapshot, reason: str) -> str:
    """Nothing was bought: ``failed`` and the money back to the balance (R9)."""
    pair = await _locked(db, snap)
    if pair is None:
        return _stale(snap, _REFUND_OUTCOMES[reason])
    order, purchase = pair
    try:
        _settle(purchase)
        await refund_to_balance(db, order=order, to_status="failed", reason=reason, actor=_ACTOR)
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    return _REFUND_OUTCOMES[reason]


__all__ = [
    "LisskinsSnapshot",
    "attention",
    "record_purchase",
    "refund",
    "retarget",
    "secure_sent",
    "switch",
    "unconfirmed",
]
