"""A Skinslink purchase's status applied to its order (spec 2026-10-06 §6).

:func:`apply_report` mirrors Skinslink's report onto ``skinslink_purchases`` and moves the
order as the status says (callers hold the order row, then the purchase row, ``FOR UPDATE``
— ruling K — and commit). :func:`check_purchase` asks Skinslink and applies the answer; the
worker's ``skinslink`` queue (:func:`drain_checks`, fed by the webhook) and the reconcile job
(``orders.skinslink_reconcile``) call it. The webhook's own body is never applied.

=====================================  ==============================================
``new``, ``pending``                   nothing
``active`` / ``hold`` with an offer    ``buying → trade_sent`` (+ the letter, a nudge)
``completed``                          ``→ delivered``
``failed``, ``canceled``               after an offer: ``returned`` + refund
                                       ``not_accepted``; before: ``failed`` + refund by
                                       the reason (low balance, trade link, sold out)
``reverted``                           delivered: attention ``rolled_back`` (the money is
                                       spent); before: ``returned`` + refund
=====================================  ==============================================

A refund an open attention blocks (R3) leaves the order as it is (``held``).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.clock import now
from csmarket.core.config import Settings, get_settings
from csmarket.core.logging import get_logger
from csmarket.modules.orders.fsm import TRANSITIONS, move
from csmarket.modules.orders.letters import enqueue_trade_sent
from csmarket.modules.orders.models import Order
from csmarket.modules.orders.public_view import public_status
from csmarket.modules.orders.refunds import refund_or_hold
from csmarket.modules.orders.trades import flag
from csmarket.modules.orders.webhook_events import emit_if_changed
from csmarket.modules.realtime.api import nudge
from csmarket.modules.skinslink.api import (
    LINK_ERROR_CODES,
    SOLD_FAIL_REASONS,
    Purchase,
    SkinslinkError,
    SkinslinkPurchase,
    SkinslinkPurchaseClient,
    SkinslinkUnavailableError,
    claim_checks,
    client_for,
)

log = get_logger("csmarket.orders.skinslink_status")

_UNITS_PER_USD = Decimal(1000)


def to_units(usd: Decimal | None) -> int | None:
    """Dollars as units (1000 = $1), half up."""
    if usd is None:
        return None
    return int((usd * _UNITS_PER_USD).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def _when(text: str | None) -> datetime | None:
    """An ISO 8601 time from Skinslink, UTC; ``None`` when absent or unreadable."""
    if not text:
        return None
    try:
        at = datetime.fromisoformat(text)
    except ValueError:
        return None
    return at if at.tzinfo is not None else at.replace(tzinfo=UTC)


def mirror_report(purchase: SkinslinkPurchase, report: Purchase) -> None:
    """Copy what Skinslink reports onto ``purchase`` (a missing field never erases ours)."""
    purchase.purchase_id = report.id
    purchase.status = report.status
    purchase.offer_id = report.offer_id or purchase.offer_id
    purchase.fail_reason = report.fail_reason or purchase.fail_reason
    purchase.amount_units = to_units(report.amount_usd) or purchase.amount_units
    purchase.hold_end_date = _when(report.hold_end_date) or purchase.hold_end_date
    purchase.last_polled_at = purchase.updated_at = now()


def link_failure_reason(code: str | None) -> str | None:
    """The refund reason for a trade-link code (a hold is ``trade_hold``), else ``None``."""
    if code in ("hold", "hold_and_permissions"):
        return "trade_hold"
    return "invalid_trade_link" if code in LINK_ERROR_CODES else None


def _failure_reason(fail_reason: str | None) -> str:
    """Why a purchase that never reached an offer failed, as the order's refund reason."""
    if fail_reason == "insufficient_balance":
        return "source_low_balance"
    link = link_failure_reason(fail_reason)
    if link is not None:
        return link
    # Only a gone or dearer offer is «sold out»; a seller who did not hand it over is not.
    return "sold_out" if fail_reason in SOLD_FAIL_REASONS else "source_refused"


async def _apply(  # noqa: PLR0911 -- one return per row of the status table
    db: AsyncSession, *, order: Order, purchase: SkinslinkPurchase, report: Purchase
) -> str:
    status = report.status
    if status in ("active", "hold"):
        if purchase.offer_id and order.status == "buying":
            move(order, "trade_sent")
            return "trade_sent"
        return "unchanged"
    if status == "completed":
        if "delivered" not in TRANSITIONS.get(order.status, frozenset()):
            return "unchanged"
        move(order, "delivered")
        return "delivered"
    if status == "reverted" and order.status == "delivered":
        if flag(purchase, "rolled_back"):
            log.error("orders.skinslink.rolled_back", number=order.number)
        return "rolled_back"
    if status in ("failed", "canceled", "reverted") and order.status in ("buying", "trade_sent"):
        if order.status == "trade_sent" or purchase.offer_id or status == "reverted":
            return await refund_or_hold(db, order, "returned", "not_accepted")
        return await refund_or_hold(db, order, "failed", _failure_reason(report.fail_reason))
    return "unchanged"


#: Outcomes that change what the buyer sees; a refund is nudged by the refund itself.
_NUDGED = frozenset({"trade_sent", "delivered", "rolled_back"})


async def apply_report(
    db: AsyncSession, *, order: Order, purchase: SkinslinkPurchase, report: Purchase
) -> str:
    """Mirror ``report`` onto ``purchase`` and move ``order`` as its status says.

    Args:
        db: Session; the caller holds ``order``, then ``purchase``, ``FOR UPDATE`` and
            commits. Never commits.
        order: The order, locked.
        purchase: Its purchase, locked.
        report: Skinslink's report of the purchase.

    Returns:
        ``unchanged``, ``trade_sent``, ``delivered``, ``returned``, ``failed``,
        ``rolled_back`` or ``held``.
    """
    before = public_status(order, None, purchase)
    mirror_report(purchase, report)
    outcome = await _apply(db, order=order, purchase=purchase, report=report)
    if outcome in _NUDGED:
        await nudge(db, user_id=order.user_id, number=order.number)
    if outcome == "trade_sent":
        await enqueue_trade_sent(db, order)
    await emit_if_changed(db, before=before, order=order, trade=None, purchase=purchase)
    return outcome


async def _lock(db: AsyncSession, order_id: str) -> tuple[Order, SkinslinkPurchase] | None:
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
    return None if order is None or purchase is None else (order, purchase)


def _settle_unseen(order: Order, purchase: SkinslinkPurchase, settings: Settings) -> str:
    """Skinslink shows no purchase under our id for a lost buy: past the wait, send the same
    ``merchant_tx_id`` again (spec §5) — Skinslink answers it with the stored purchase, a new
    one, or a refusal, so the buy path settles it. A silence is never refunded."""
    unseen = purchase.buy_unconfirmed_at
    purchase.last_polled_at = now()
    if unseen is None or purchase.purchase_id is not None or order.status != "buying":
        return "unchanged"
    if now() - unseen < timedelta(minutes=settings.order_unconfirmed_minutes):
        return "unchanged"
    purchase.buy_unconfirmed_at = None
    purchase.buy_pending = True
    order.next_check_at = None  # due for the reconcile's buy at once
    log.warning("orders.skinslink.repeat_unseen", number=order.number)
    return "repeat"


async def check_purchase(
    db: AsyncSession,
    client: SkinslinkPurchaseClient,
    *,
    purchase_id: int | None = None,
    order_id: str | None = None,
    settings: Settings | None = None,
) -> str:
    """Ask Skinslink about one purchase and apply the answer; commits.

    Found by ``purchase_id`` (a webhook) or ``order_id`` (the reconcile). A purchase whose
    buy is still pending is left to the buy path. No lock is held across the call.

    Returns:
        :func:`apply_report`'s outcome, ``repeat`` (a lost buy is sent again), ``unknown``
        (no such purchase) or ``unavailable`` (Skinslink did not answer).
    """
    settings = settings or get_settings()
    where = (
        SkinslinkPurchase.purchase_id == purchase_id
        if purchase_id is not None
        else SkinslinkPurchase.order_id == order_id
    )
    row = await db.scalar(select(SkinslinkPurchase).where(where))
    found = None if row is None else (row.order_id, row.merchant_tx_id, row.buy_pending)
    await db.commit()
    if found is None:
        # A webhook about a purchase we hold no id for: logged, never applied blind.
        log.warning("orders.skinslink.unknown_purchase")
        return "unknown"
    oid, tx, pending = found
    if pending:
        return "unchanged"
    try:
        report = await client.purchase_status(merchant_tx_id=tx)
    except (SkinslinkError, SkinslinkUnavailableError) as exc:
        log.warning("orders.skinslink.check_failed", error=type(exc).__name__)
        return "unavailable"
    pair = await _lock(db, oid)
    if pair is None or pair[1].buy_pending:  # pragma: no cover - moved during the call
        await db.commit()
        return "unchanged"
    order, purchase = pair
    if report is None:
        outcome = _settle_unseen(order, purchase, settings)
    else:
        purchase.buy_unconfirmed_at = None
        outcome = await apply_report(db, order=order, purchase=purchase, report=report)
    await db.commit()
    if outcome != "unchanged":
        log.info("orders.skinslink.checked", number=order.number, outcome=outcome)
    return outcome


async def drain_checks(
    db: AsyncSession,
    *,
    client: SkinslinkPurchaseClient | None = None,
    settings: Settings | None = None,
    limit: int = 20,
) -> int:
    """The worker's ``skinslink`` drain: take queued checks and ask Skinslink about each.

    Returns:
        How many checks were taken (0 = the queue is dry).
    """
    settings = settings or get_settings()
    ids = await claim_checks(db, limit=limit)
    await db.commit()
    # The key, not the switch: open orders still settle after Skinslink is switched off.
    if not ids or (client is None and not settings.skinslink_api_key):
        return len(ids)
    client = client or client_for(settings)
    for pid in ids:
        try:
            await check_purchase(db, client, purchase_id=pid, settings=settings)
        except Exception as exc:  # noqa: BLE001 -- one bad check must not stop the batch
            await db.rollback()
            log.error("orders.skinslink.check_crashed", error=type(exc).__name__)  # noqa: TRY400
    return len(ids)


__all__ = ["apply_report", "check_purchase", "drain_checks", "mirror_report", "to_units"]
