"""The nightly erase (decision D3, M4b ruling R11): what we no longer need, we do not keep.

- :func:`erase_old_trade_links` — 30 days after an order ends (``delivered_at``,
  ``cancelled_at`` or ``failed_at``), its ``trade_link`` becomes the masked form
  (``partner`` kept, the token's last two characters only) and ``trade_link_erased_at`` is
  stamped; a stored value that does not parse becomes ``erased``. Batches of 500 claimed
  ``FOR UPDATE SKIP LOCKED``, each committed. Nothing reads ``trade_link`` for an order
  that has ended.
- :func:`erase_old_verify_addresses` — a ``verify`` outbox row's address (the one email
  the outbox snapshots) is dropped a week after it was queued; its link died after 24 h.

Both are idempotent. Log lines carry counts only.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.logging import get_logger
from csmarket.modules.notifications.models import EmailOutbox
from csmarket.modules.orders.models import TERMINAL, Order
from csmarket.modules.users.api import mask_trade_link

log = get_logger("csmarket.orders.erase")

#: What a link that does not parse is replaced with.
ERASED = "erased"
#: How long a ``verify`` letter's address is kept.
VERIFY_ADDRESS_KEPT = timedelta(days=7)


async def erase_old_trade_links(
    db: AsyncSession,
    *,
    at: datetime,
    older_than: timedelta = timedelta(days=30),
    batch: int = 500,
) -> int:
    """Mask the trade link of every order that ended before ``at − older_than``; commits.

    Returns:
        How many orders were erased.
    """
    ended = func.coalesce(Order.delivered_at, Order.cancelled_at, Order.failed_at)
    total = 0
    while True:
        orders = (
            await db.scalars(
                select(Order)
                .where(
                    Order.status.in_(TERMINAL),
                    Order.trade_link_erased_at.is_(None),
                    ended < at - older_than,
                )
                .order_by(ended)
                .limit(batch)
                .with_for_update(skip_locked=True)
            )
        ).all()
        for order in orders:
            masked = mask_trade_link(order.trade_link)
            order.trade_link = masked if masked and "partner=" in masked else ERASED
            order.trade_link_erased_at = at
        await db.commit()
        total += len(orders)
        if len(orders) < batch:
            break
    if total:
        log.info("orders.erase.trade_links", count=total)
    return total


async def erase_old_verify_addresses(db: AsyncSession, *, at: datetime) -> int:
    """Drop the address of ``verify`` letters queued over a week before ``at``; commits.

    Returns:
        How many rows lost their address.
    """
    result = await db.execute(
        update(EmailOutbox)
        .where(
            EmailOutbox.kind == "verify",
            EmailOutbox.address.is_not(None),
            EmailOutbox.created_at < at - VERIFY_ADDRESS_KEPT,
        )
        .values(address=None)
    )
    await db.commit()
    count = int(getattr(result, "rowcount", 0) or 0)  # CursorResult; typed as Result
    if count:
        log.info("orders.erase.verify_addresses", count=count)
    return count


__all__ = ["ERASED", "erase_old_trade_links", "erase_old_verify_addresses"]
