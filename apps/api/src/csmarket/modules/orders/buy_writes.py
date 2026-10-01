"""The buy's writes (``orders.buying``): lock the order, then its trade (ruling K), re-check
``status == "buying"`` and ``buy_pending``, write, commit — and write nothing when a sweep
moved the rows during the Waxpeer call. Each returns the attempt's outcome.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.clock import now
from csmarket.core.logging import get_logger
from csmarket.core.metrics import TradeAttentionReason
from csmarket.modules.orders.models import Order, SkinTrade
from csmarket.modules.orders.refunds import refund_to_balance
from csmarket.modules.orders.trades import FAILED_STATUS, flag, mirror
from csmarket.modules.skins.api import WaxpeerBuy, WaxpeerTrade

log = get_logger("csmarket.orders.buying")

_ACTOR = "orders"
#: Refund reason → outcome.
_REFUND_OUTCOMES: dict[str, str] = {
    "invalid_trade_link": "invalid_link",
    "sold_out": "sold_out",
    "waxpeer_low_balance": "low_balance",
}


class BuySnapshot(BaseModel):
    """What a buy needs of the order, read unlocked before Waxpeer is called."""

    model_config = ConfigDict(frozen=True)

    order_id: str
    number: str
    skin_item_id: str
    listing_id: int
    paid_units: int
    #: A buy's answer was lost before (``buy_unconfirmed_at``): a lookup decides, not a buy.
    unconfirmed: bool = False


async def _lock_both(db: AsyncSession, order_id: str) -> tuple[Order | None, SkinTrade | None]:
    """The order, then its trade, ``FOR UPDATE`` (ruling K), read fresh."""
    order = await db.scalar(
        select(Order)
        .where(Order.id == order_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    trade = await db.scalar(
        select(SkinTrade)
        .where(SkinTrade.order_id == order_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return order, trade


async def _locked(db: AsyncSession, snap: BuySnapshot) -> tuple[Order, SkinTrade] | None:
    """The order and its trade ``FOR UPDATE`` if still ``buying`` with a buy pending."""
    order, trade = await _lock_both(db, snap.order_id)
    if order is None or trade is None or order.status != "buying" or not trade.buy_pending:
        await db.commit()  # nothing written: just let the locks go
        return None
    return order, trade


def _stale(snap: BuySnapshot, outcome: str) -> str:
    """Someone moved the rows during the Waxpeer call, and nothing was bought: write nothing."""
    log.warning("orders.buy.stale", number=snap.number, outcome=outcome)
    return "nothing_to_do"


async def _stale_purchase(db: AsyncSession, snap: BuySnapshot, waxpeer_id: int | None) -> str:
    """A buy that may have gone through landed on rows someone else moved: never silent.

    The same purchase already on record (same Waxpeer id) is fine. Otherwise a second
    purchase may exist outside our record: the trade gets the ``ambiguous_trade`` attention
    (which also blocks any automatic refund, R3) and an error is logged — number only.
    """
    order, trade = await _lock_both(db, snap.order_id)
    if order is None or trade is None:  # pragma: no cover - a foreign key
        await db.commit()
        return "stale_bought"
    if waxpeer_id is not None and trade.waxpeer_id == waxpeer_id:
        await db.commit()
        return "bought"
    flag(trade, "ambiguous_trade", reopen=True)
    await db.commit()
    log.error("orders.buy.stale_purchase", number=snap.number)
    return "stale_bought"


def _settle(trade: SkinTrade) -> None:
    """The buy is no longer pending; a ``waxpeer_forbidden`` attention is moot now."""
    trade.buy_pending = False
    if trade.attention_reason == "waxpeer_forbidden":
        trade.attention_reason = None
        trade.resolved_at = trade.resolved_by = trade.resolved_note = None
    trade.updated_at = now()


async def secure_sent(db: AsyncSession, snap: BuySnapshot) -> bool:
    """A buy this attempt sent but could not record: never leave it ``buy_pending``.

    Marks the trade unconfirmed (resolved by lookup, never rebought, R3) — and, on an order
    that left ``buying`` meanwhile, flags ``ambiguous_trade``. A trade whose buy is no
    longer pending already has its outcome on record: nothing to do.

    Returns:
        Whether this call marked the trade.
    """
    order, trade = await _lock_both(db, snap.order_id)
    marked = order is not None and trade is not None and trade.buy_pending
    if marked and order is not None and trade is not None:
        _settle(trade)
        trade.buy_unconfirmed_at = now()
        if order.status != "buying":
            flag(trade, "ambiguous_trade", reopen=True)
    await db.commit()
    return marked


async def record_bought(
    db: AsyncSession, snap: BuySnapshot, bought: WaxpeerBuy, *, listing_id: int, units: int
) -> str:
    """Waxpeer accepted the buy: its id, the listing and units actually bought."""
    pair = await _locked(db, snap)
    if pair is None:
        return await _stale_purchase(db, snap, bought.id)
    _, trade = pair
    trade.listing_id, trade.paid_units = listing_id, units
    trade.waxpeer_id, trade.status = bought.id, 0
    trade.bought_units = bought.price_units or units  # Waxpeer may answer ``price: 0``
    _settle(trade)
    await db.commit()
    return "bought"


async def adopt(db: AsyncSession, snap: BuySnapshot, found: WaxpeerTrade) -> str:
    """A lookup found an earlier purchase under our ``project_id``: mirror it, never rebuy."""
    pair = await _locked(db, snap)
    if pair is None:
        return _stale(snap, "adopted")
    _, trade = pair
    mirror(trade, found)
    if trade.bought_units is None and found.status != FAILED_STATUS and found.price_units > 0:
        trade.bought_units = found.price_units
    _settle(trade)
    await db.commit()
    return "adopted"


async def park(db: AsyncSession, snap: BuySnapshot) -> str:
    """An earlier buy's answer was lost and the lookup shows only failed trades: buy nothing,
    end the pending buy, and let the reconcile sweep's unconfirmed rule decide (R3)."""
    pair = await _locked(db, snap)
    if pair is None:
        return _stale(snap, "nothing_to_do")
    _, trade = pair
    _settle(trade)
    await db.commit()
    log.warning("orders.buy.parked", number=snap.number)
    return "nothing_to_do"


async def unconfirmed(db: AsyncSession, snap: BuySnapshot) -> str:
    """The buy's answer was lost: resolve by lookup (R3), never by buying again.

    Rows moved meanwhile: the lost request may still have bought — flagged, never silent.
    """
    pair = await _locked(db, snap)
    if pair is None:
        return await _stale_purchase(db, snap, None)
    _, trade = pair
    _settle(trade)
    trade.buy_unconfirmed_at = now()
    await db.commit()
    return "unconfirmed"


async def attention(
    db: AsyncSession,
    snap: BuySnapshot,
    reason: TradeAttentionReason,
    *,
    outcome: str,
    settle: bool = False,
) -> str:
    """Flag the trade for an admin; ``settle`` ends the pending buy too.

    Once per open attention: a resolved one with the same reason is re-opened (a 403 after
    an operator resolved it means the access is still broken — an admin refund must not
    treat the order as settled).
    """
    pair = await _locked(db, snap)
    if pair is None:
        return _stale(snap, outcome)
    _, trade = pair
    if settle:
        _settle(trade)
    flag(trade, reason, reopen=True)
    await db.commit()
    return outcome


async def refund(db: AsyncSession, snap: BuySnapshot, reason: str) -> str:
    """Nothing was bought: ``failed`` and the money back to the balance (R9)."""
    pair = await _locked(db, snap)
    if pair is None:
        return _stale(snap, _REFUND_OUTCOMES[reason])
    order, trade = pair
    try:
        _settle(trade)
        await refund_to_balance(db, order=order, to_status="failed", reason=reason, actor=_ACTOR)
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    return _REFUND_OUTCOMES[reason]


__all__ = [
    "BuySnapshot",
    "adopt",
    "attention",
    "park",
    "record_bought",
    "refund",
    "secure_sent",
    "unconfirmed",
]
