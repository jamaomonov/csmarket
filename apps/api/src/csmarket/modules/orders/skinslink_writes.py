"""The Skinslink buy's writes (``orders.skinslink_buying``): lock the order, then its purchase
(ruling K), re-check ``status == "buying"`` and ``buy_pending``, write, commit — and write
nothing when a sweep moved the rows during the Skinslink call. Each returns the outcome.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.clock import now
from csmarket.core.logging import get_logger
from csmarket.core.metrics import TradeAttentionReason
from csmarket.modules.orders.models import Order
from csmarket.modules.orders.refunds import refund_to_balance
from csmarket.modules.orders.skinslink_status import apply_report
from csmarket.modules.orders.trades import flag
from csmarket.modules.skinslink.api import Purchase, SkinslinkPurchase

log = get_logger("csmarket.orders.skinslink_buying")

_ACTOR = "orders"
#: Refund reason → outcome.
_REFUND_OUTCOMES: dict[str, str] = {
    "invalid_trade_link": "invalid_link",
    "sold_out": "sold_out",
    "source_low_balance": "low_balance",
}


class PurchaseSnapshot(BaseModel):
    """What a Skinslink buy needs of the order, read unlocked before Skinslink is called."""

    model_config = ConfigDict(frozen=True)

    order_id: str
    number: str
    skin_item_id: str
    merchant_tx_id: str
    asset_id: str
    paid_units: int
    #: The order's agreed cost.
    cost_units: int


async def _lock_both(
    db: AsyncSession, order_id: str
) -> tuple[Order | None, SkinslinkPurchase | None]:
    """The order, then its purchase, ``FOR UPDATE`` (ruling K), read fresh."""
    order = await db.scalar(
        select(Order)
        .where(Order.id == order_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    purchase = await db.scalar(
        select(SkinslinkPurchase)
        .where(SkinslinkPurchase.order_id == order_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return order, purchase


async def _locked(
    db: AsyncSession, snap: PurchaseSnapshot
) -> tuple[Order, SkinslinkPurchase] | None:
    """Both rows ``FOR UPDATE`` if still ``buying`` with the buy pending; else ``None``."""
    order, purchase = await _lock_both(db, snap.order_id)
    if order is None or purchase is None or order.status != "buying" or not purchase.buy_pending:
        await db.commit()  # nothing written: just let the locks go
        return None
    return order, purchase


def _stale(snap: PurchaseSnapshot, outcome: str) -> str:
    """Someone moved the rows during the call, and nothing was bought: write nothing."""
    log.warning("orders.skinslink_buy.stale", number=snap.number, outcome=outcome)
    return "nothing_to_do"


async def _stale_purchase(db: AsyncSession, snap: PurchaseSnapshot) -> str:
    """A purchase that may have gone through landed on moved rows: flagged, never silent."""
    order, purchase = await _lock_both(db, snap.order_id)
    if order is not None and purchase is not None:
        flag(purchase, "ambiguous_trade", reopen=True)
    await db.commit()
    log.error("orders.skinslink_buy.stale_purchase", number=snap.number)
    return "stale_bought"


def _settle(purchase: SkinslinkPurchase) -> None:
    """The buy is no longer pending; a ``source_forbidden`` attention is moot now."""
    purchase.buy_pending = False
    if purchase.attention_reason == "source_forbidden":
        purchase.attention_reason = None
        purchase.resolved_at = purchase.resolved_by = purchase.resolved_note = None
    purchase.updated_at = now()


async def record_purchase(
    db: AsyncSession, snap: PurchaseSnapshot, report: Purchase, *, outcome: str = "bought"
) -> str:
    """Skinslink took the purchase (or a repeat named it): record it, apply its status."""
    pair = await _locked(db, snap)
    if pair is None:
        return await _stale_purchase(db, snap)
    order, purchase = pair
    _settle(purchase)
    purchase.buy_unconfirmed_at = None
    await apply_report(db, order=order, purchase=purchase, report=report)
    await db.commit()
    return outcome


async def unconfirmed(db: AsyncSession, snap: PurchaseSnapshot) -> str:
    """The purchase's answer was lost: resolved by repeating the same ``merchant_tx_id``."""
    pair = await _locked(db, snap)
    if pair is None:
        return await _stale_purchase(db, snap)
    _, purchase = pair
    _settle(purchase)
    purchase.buy_unconfirmed_at = now()
    await db.commit()
    return "unconfirmed"


async def secure_sent(db: AsyncSession, snap: PurchaseSnapshot) -> bool:
    """A purchase this attempt sent but could not record: never leave it ``buy_pending``."""
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
    db: AsyncSession, snap: PurchaseSnapshot, reason: TradeAttentionReason, *, outcome: str
) -> str:
    """Flag the purchase for an admin; the buy stays pending."""
    pair = await _locked(db, snap)
    if pair is None:
        return _stale(snap, outcome)
    flag(pair[1], reason, reopen=True)
    await db.commit()
    return outcome


async def refund(db: AsyncSession, snap: PurchaseSnapshot, reason: str) -> str:
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
    "PurchaseSnapshot",
    "attention",
    "record_purchase",
    "refund",
    "secure_sent",
    "unconfirmed",
]
