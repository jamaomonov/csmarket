"""A LIS-SKINS purchase's status applied to its order (spec 2026-10-07 §6).

:func:`apply_report` mirrors LIS-SKINS' report onto ``lisskins_purchases`` and moves the
order as the skin's status says. Callers hold the order row, then the purchase row,
``FOR UPDATE`` (ruling K) and commit. The buy (``lisskins_writes``) and the reconcile
(``lisskins_reconcile``) call it; there is no webhook.

==========================================  ==================================================
``processing``                              nothing
``wait_accept`` with an offer               ``buying → trade_sent`` (+ the letter with the
                                            offer's expiry, a nudge)
``accepted``                                ``→ delivered``
``return``, ``rollback_…`` / after delivery attention ``rolled_back`` (the skin may be spent)
``return``, ``trade_create_error``, before  ``failed`` + refund ``invalid_trade_link`` (a link
an offer                                    error) or ``source_refused``
``return``, any other reason                ``returned`` + refund ``not_accepted``
``wait_unlock`` / ``wait_withdraw``         attention ``ambiguous_trade`` (we never buy
                                            locked lots)
==========================================  ==================================================

A refund an open attention blocks (R3) leaves the order as it is (``held``).
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.clock import now
from csmarket.core.logging import get_logger
from csmarket.core.redis import get_redis
from csmarket.modules.lisskins.api import (
    TRADE_LINK_ERRORS,
    LisskinsPurchase,
    Purchase,
    PurchasedSkin,
    remember_rejection,
    to_units,
)
from csmarket.modules.orders.fsm import TRANSITIONS, move
from csmarket.modules.orders.letters import enqueue_trade_sent
from csmarket.modules.orders.models import Order
from csmarket.modules.orders.public_view import public_status
from csmarket.modules.orders.refunds import refund_or_hold
from csmarket.modules.orders.trades import flag
from csmarket.modules.orders.webhook_events import emit_if_changed
from csmarket.modules.realtime.api import nudge

log = get_logger("csmarket.orders.lisskins_status")

#: Outcomes that change what the buyer sees; a refund is nudged by the refund itself.
_NUDGED = frozenset({"trade_sent", "delivered", "rolled_back", "ambiguous"})


def _when(text: str | None) -> datetime | None:
    """An ISO 8601 time from LIS-SKINS, UTC; ``None`` when absent or unreadable."""
    if not text:
        return None
    try:
        at = datetime.fromisoformat(text)
    except ValueError:
        return None
    return at if at.tzinfo is not None else at.replace(tzinfo=UTC)


#: The ``lisskins_purchases`` column widths: ``status`` and the other reported words.
_STATUS_MAX, _TEXT_MAX = 16, 32


def _cut(text: str | None, limit: int) -> str | None:
    """``text`` cut to its column: an oversized word must not fail the order's write."""
    return None if text is None else text[:limit]


def mirror_report(purchase: LisskinsPurchase, report: Purchase) -> PurchasedSkin:
    """Copy what LIS-SKINS reports onto ``purchase`` (a missing field never erases ours);
    returns the skin the order bought."""
    skin = next((s for s in report.skins if s.id == purchase.skin_id), report.skin)
    purchase.purchase_id = report.purchase_id
    purchase.status = _cut(skin.status, _STATUS_MAX)
    purchase.return_reason = _cut(skin.return_reason, _TEXT_MAX) or purchase.return_reason
    purchase.error = _cut(skin.error, _TEXT_MAX) or purchase.error
    purchase.steam_trade_offer_id = _cut(skin.offer_id, _TEXT_MAX) or purchase.steam_trade_offer_id
    purchase.offer_expiry_at = _when(skin.offer_expiry_at) or purchase.offer_expiry_at
    if skin.price_usd is not None:
        purchase.amount_units = to_units(skin.price_usd)
    purchase.last_polled_at = purchase.updated_at = now()
    return skin


async def _returned(
    db: AsyncSession, *, order: Order, purchase: LisskinsPurchase, skin: PurchasedSkin
) -> str:
    reason = skin.return_reason or ""
    # Both rollback reasons (the buyer's and the seller's) undo an accepted trade: the skin
    # may have been used — an admin decides, never an automatic refund.
    if reason.startswith("rollback_") or order.status == "delivered":
        if flag(purchase, "rolled_back"):
            log.error("orders.lisskins.rolled_back", number=order.number)
            return "rolled_back"
        return "unchanged"
    if order.status not in ("buying", "trade_sent"):
        return "unchanged"
    if reason == "trade_create_error" and order.status == "buying":
        why = "invalid_trade_link" if skin.error in TRADE_LINK_ERRORS else "source_refused"
        if why == "invalid_trade_link" and skin.error != "user_inventory_full":
            await remember_rejection(get_redis(), order.trade_link)  # the partner API hears it
        return await refund_or_hold(db, order, "failed", why)
    return await refund_or_hold(db, order, "returned", "not_accepted")


async def _apply(  # noqa: PLR0911 -- one return per row of the status table
    db: AsyncSession, *, order: Order, purchase: LisskinsPurchase, skin: PurchasedSkin
) -> str:
    if skin.status == "wait_accept":
        if skin.offer_id and order.status == "buying":
            move(order, "trade_sent")
            return "trade_sent"
        return "unchanged"
    if skin.status == "accepted":
        if "delivered" not in TRANSITIONS.get(order.status, frozenset()):
            return "unchanged"
        move(order, "delivered")
        return "delivered"
    if skin.status in ("wait_unlock", "wait_withdraw"):
        return "ambiguous" if flag(purchase, "ambiguous_trade") else "unchanged"
    if skin.status == "return":
        return await _returned(db, order=order, purchase=purchase, skin=skin)
    return "unchanged"  # processing, or a word LIS-SKINS adds later


async def apply_report(
    db: AsyncSession, *, order: Order, purchase: LisskinsPurchase, report: Purchase
) -> str:
    """Mirror ``report`` onto ``purchase`` and move ``order`` as the table above says.

    Args:
        db: Session; the caller holds ``order``, then ``purchase``, ``FOR UPDATE`` and
            commits. Never commits.
        order: The order, locked.
        purchase: Its purchase, locked.
        report: LIS-SKINS' report of the purchase.

    Returns:
        ``unchanged``, ``trade_sent``, ``delivered``, ``returned``, ``failed``,
        ``rolled_back``, ``ambiguous`` or ``held``.
    """
    before = public_status(order, None, purchase)
    skin = mirror_report(purchase, report)
    outcome = await _apply(db, order=order, purchase=purchase, skin=skin)
    if outcome in _NUDGED:
        await nudge(db, user_id=order.user_id, number=order.number)
    if outcome == "trade_sent":
        await enqueue_trade_sent(db, order, send_until=purchase.offer_expiry_at)
    await emit_if_changed(db, before=before, order=order, trade=None, purchase=purchase)
    return outcome


async def lock(db: AsyncSession, order_id: str) -> tuple[Order, LisskinsPurchase] | None:
    """The order, then its purchase, ``FOR UPDATE`` (ruling K), read fresh."""
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
    return None if order is None or purchase is None else (order, purchase)


__all__ = ["apply_report", "lock", "mirror_report"]
