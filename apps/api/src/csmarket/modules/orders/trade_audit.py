"""The nightly history audit (the scheduler's ``trades.audit``, ruling R5): the last 14 days
of settled trades read again from Waxpeer; each divergence is recorded once
(``audit_verdict``) and opens the attention ``audit_divergence``.
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.clock import now
from csmarket.core.logging import get_logger
from csmarket.core.metrics import record_trade_attention
from csmarket.modules.orders.models import Order, SkinTrade
from csmarket.modules.orders.sweep_base import (
    LOOKUP_ERRORS,
    SweepRow,
    crashed,
    lock_both,
    lookup,
    of_project,
)
from csmarket.modules.orders.trades import (
    FAILED_STATUS,
    RELEASED_STATUS,
    AmbiguousTradeError,
    flag,
    pick_trade,
)
from csmarket.modules.skins.api import TradeClient, WaxpeerTrade

log = get_logger("csmarket.orders.audit")

#: How far back the history audit reads.
AUDIT_DAYS = 14


def _verdict(order: Order, trade: SkinTrade, theirs: list[WaxpeerTrade]) -> str | None:
    """How Waxpeer disagrees with a trade we consider settled; ``None`` when it agrees."""
    try:
        wt = pick_trade(theirs, trade.waxpeer_id)
    except AmbiguousTradeError:
        return "ambiguous"
    if wt is None:
        # A trade that never reached Waxpeer (sold out before any buy) is fine.
        return "unknown" if trade.status is not None else None
    refunded = order.refunded_at is not None
    if (
        wt.status == FAILED_STATUS
        and not refunded
        and order.status == "delivered"
        and trade.status != FAILED_STATUS  # a rollback the sweeps saw is already flagged
    ):
        return "rolled_back"
    if refunded and wt.status != FAILED_STATUS:
        # Any trade of ours that is not a failed one: the skin may reach (or have reached)
        # the buyer although the money is back on the balance.
        return "delivered_refunded"
    return None


async def _audit_one(db: AsyncSession, row: SweepRow, theirs: list[WaxpeerTrade]) -> int:
    """Record a changed verdict on one trade; 1 when it is a new divergence."""
    order, trade = await lock_both(db, row.order_id)
    if order is None or trade is None:  # pragma: no cover - a foreign key
        await db.commit()
        return 0
    verdict = _verdict(order, trade, theirs)
    if verdict == trade.audit_verdict:
        await db.commit()  # one alert per verdict, not one per night in the window
        return 0
    trade.audit_verdict = verdict
    trade.updated_at = now()
    if verdict is not None and not flag(trade, "audit_divergence", reopen=True):
        record_trade_attention("audit_divergence")  # a new verdict alerts even when flagged
    await db.commit()
    if verdict is None:
        return 0
    log.warning("orders.audit.divergence", number=order.number, verdict=verdict)
    return 1


async def audit_recent(db: AsyncSession, client: TradeClient, *, days: int = AUDIT_DAYS) -> int:
    """Read the last ``days`` of settled trades again and record every divergence once.

    Settled: Waxpeer status 5 or 6, released, or the order ``failed`` / ``returned``.
    Verdicts: ``unknown`` (Waxpeer has no record of a trade we saw), ``rolled_back``
    (Waxpeer 6, the order delivered and not refunded), ``delivered_refunded`` (the order
    refunded while its Waxpeer trade is anything but a 6: 0–5, the skin may reach the
    buyer), ``ambiguous``. A new verdict is stored in ``audit_verdict``,
    opens the attention ``audit_divergence`` and counts the metric; agreement clears the
    verdict. Changes no trade or order state otherwise.

    Args:
        db: Session; each changed verdict is committed in its own transaction.
        client: Waxpeer; asked in batches of :data:`LOOKUP_MAX_IDS`.
        days: How far back to look.

    Returns:
        How many new divergences were recorded; 0 when Waxpeer could not be read (then
        nothing is written).
    """
    rows = [
        SweepRow(order_id=r[0], project_id=r[1])
        for r in (
            await db.execute(
                select(Order.id, SkinTrade.project_id)
                .join(SkinTrade, SkinTrade.order_id == Order.id)
                .where(
                    SkinTrade.created_at >= now() - timedelta(days=days),
                    or_(
                        SkinTrade.status.in_((RELEASED_STATUS, FAILED_STATUS)),
                        SkinTrade.is_released.is_(True),
                        Order.status.in_(("failed", "returned")),
                    ),
                )
                .order_by(SkinTrade.created_at, SkinTrade.order_id)
            )
        ).all()
    ]
    await db.commit()
    try:
        found = await lookup(client, [r.project_id for r in rows])
    except LOOKUP_ERRORS as exc:
        log.warning("orders.audit.unavailable", error=type(exc).__name__, trades=len(rows))
        return 0
    diverged = 0
    for row in rows:
        try:
            diverged += await _audit_one(db, row, of_project(found, row.project_id))
        except Exception as exc:  # noqa: BLE001 -- one bad row must not stop the audit
            await db.rollback()
            crashed("orders.audit.crashed", row.order_id, exc)
    log.info("orders.audit.done", trades=len(rows), diverged=diverged)
    return diverged


__all__ = ["AUDIT_DAYS", "audit_recent"]
