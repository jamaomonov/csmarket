"""A Skinslink purchase's status applied to its order (spec 2026-10-06 §6).

:func:`apply_report` mirrors Skinslink's report onto ``skinslink_purchases`` and moves the
order as the status says. Callers hold the order row and then the purchase row
``FOR UPDATE`` (ruling K) and commit.

=============================  ===============================================
``new``, ``pending``           nothing
``active`` with an offer id    ``buying → trade_sent`` (+ the letter, a nudge)
=============================  ===============================================
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.clock import now
from csmarket.modules.orders.fsm import TRANSITIONS, move
from csmarket.modules.orders.letters import enqueue_trade_sent
from csmarket.modules.orders.models import Order
from csmarket.modules.realtime.api import nudge
from csmarket.modules.skinslink.api import Purchase, SkinslinkPurchase

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


async def apply_report(
    db: AsyncSession, *, order: Order, purchase: SkinslinkPurchase, report: Purchase
) -> str:
    """Mirror ``report`` onto ``purchase`` and move ``order`` as its status says.

    Args:
        db: Session; the caller holds ``order``, then ``purchase``, ``FOR UPDATE``.
        order: The order, locked.
        purchase: Its purchase, locked.
        report: Skinslink's report of the purchase.

    Returns:
        ``unchanged`` or ``trade_sent``.
    """
    mirror_report(purchase, report)
    if report.status != "active" or not purchase.offer_id:
        return "unchanged"
    if "trade_sent" not in TRANSITIONS.get(order.status, frozenset()):
        return "unchanged"  # already there, or settled
    move(order, "trade_sent")
    await nudge(db, user_id=order.user_id, number=order.number)
    await enqueue_trade_sent(db, order)
    return "trade_sent"


__all__ = ["apply_report", "mirror_report", "to_units"]
