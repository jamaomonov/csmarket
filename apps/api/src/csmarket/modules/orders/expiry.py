"""Unpaid orders past ``expires_at`` → ``cancelled`` (the scheduler's ``orders.expiry``)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.clock import now
from csmarket.core.logging import get_logger
from csmarket.modules.orders.fsm import move
from csmarket.modules.orders.models import Order
from csmarket.modules.realtime.api import nudge

log = get_logger("csmarket.orders.expiry")

#: Payment attempts a kassa holds (or that already paid): the order is not expired.
_HELD = ("pending", "succeeded")


async def expire_pending(db: AsyncSession, *, batch: int = 500) -> int:
    """Cancel unpaid orders past ``expires_at`` that no kassa holds.

    Locks the candidates ``FOR UPDATE SKIP LOCKED`` (a kassa or a pay call mid-flight holds
    its order: skipped, not waited for), re-reads their attempts under the lock, and keeps
    any order a kassa took up meanwhile — a held attempt closes by the kassa's own timeout
    (M3 R8), and the order then expires on a later tick. ``created`` attempts are cancelled
    through ``payments.cancel_pending``. Flushes, never commits.

    Args:
        db: Session; the caller commits.
        batch: Orders per call; the next tick continues a backlog.

    Returns:
        How many orders went ``cancelled``.
    """
    # Lazy: ``payments`` imports ``orders.api``; importing it here at load time would close
    # the cycle (ruling A).
    from csmarket.modules.payments.api import Payment, cancel_pending

    held = (
        select(Payment.id).where(Payment.order_id == Order.id, Payment.status.in_(_HELD)).exists()
    )
    candidates = list(
        (
            await db.scalars(
                select(Order)
                .where(Order.status == "pending", Order.expires_at < now(), ~held)
                .order_by(Order.expires_at)
                .limit(batch)
                .with_for_update(skip_locked=True)
                .execution_options(populate_existing=True)
            )
        ).all()
    )
    if not candidates:
        return 0
    attempts: dict[str, list[Payment]] = {}
    for attempt in await db.scalars(
        select(Payment)
        .where(Payment.order_id.in_([o.id for o in candidates]))
        .execution_options(populate_existing=True)
    ):
        attempts.setdefault(str(attempt.order_id), []).append(attempt)
    expired = 0
    for order in candidates:
        rows = attempts.get(order.id, [])
        if any(a.status in _HELD for a in rows):
            continue  # a kassa took it up after the candidate query's snapshot
        for attempt in rows:
            if attempt.status == "created":
                await cancel_pending(db, payment=attempt)
        move(order, "cancelled")
        await nudge(db, user_id=order.user_id, number=order.number)
        expired += 1
        log.info("orders.expired", number=order.number)
    await db.flush()
    return expired


__all__ = ["expire_pending"]
