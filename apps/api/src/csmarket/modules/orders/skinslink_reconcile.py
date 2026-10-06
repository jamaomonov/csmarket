"""The Skinslink reconcile (spec 2026-10-06 §6): the fallback when a webhook is lost.

Every open Skinslink order (``buying`` / ``trade_sent``) whose purchase was not polled for
:data:`POLL_EVERY`, or whose buy's answer was lost, is asked about again
(``skinslink_status.check_purchase``); one whose buy is still pending is bought
(``skinslink_buying.attempt_skinslink_buy`` — its lease decides whether anyone else is on it).
Each order gets its own session: one failure never stops the tick.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.clock import now
from csmarket.core.config import Settings
from csmarket.core.logging import get_logger
from csmarket.modules.orders.models import Order
from csmarket.modules.orders.skinslink_buying import attempt_skinslink_buy
from csmarket.modules.orders.skinslink_status import check_purchase
from csmarket.modules.skins.api import TradeClient
from csmarket.modules.skinslink.api import SkinslinkPurchase, SkinslinkPurchaseClient

log = get_logger("csmarket.orders.skinslink_reconcile")

#: How long an open purchase goes unpolled before the reconcile asks about it.
POLL_EVERY = timedelta(seconds=30)
#: Orders per tick.
BATCH = 50

SessionFactory = Callable[[], AsyncSession]


async def _due(db: AsyncSession) -> list[tuple[str, bool]]:
    """``(order id, buy_pending)`` of the open purchases due a poll; ends the transaction."""
    stale = now() - POLL_EVERY
    rows = await db.execute(
        select(SkinslinkPurchase.order_id, SkinslinkPurchase.buy_pending)
        .join(Order, Order.id == SkinslinkPurchase.order_id)
        .where(
            Order.status.in_(("buying", "trade_sent")),
            or_(
                SkinslinkPurchase.buy_pending.is_(True),
                SkinslinkPurchase.buy_unconfirmed_at.is_not(None),
                SkinslinkPurchase.last_polled_at.is_(None),
                SkinslinkPurchase.last_polled_at <= stale,
            ),
        )
        .order_by(SkinslinkPurchase.last_polled_at.asc().nulls_first(), Order.created_at)
        .limit(BATCH)
    )
    due = [(r[0], r[1]) for r in rows.all()]
    await db.commit()
    return due


async def reconcile_skinslink(
    db_factory: SessionFactory,
    client: SkinslinkPurchaseClient,
    *,
    settings: Settings,
    waxpeer: TradeClient | None = None,
) -> int:
    """One tick: poll or buy every due Skinslink order.

    Args:
        db_factory: Makes a session per order.
        client: Skinslink.
        settings: Settings.
        waxpeer: Waxpeer, for a buy's substitute search.

    Returns:
        How many orders the tick looked at.
    """
    async with db_factory() as db:
        due = await _due(db)
    for order_id, pending in due:
        try:
            async with db_factory() as db:
                if pending:
                    await attempt_skinslink_buy(
                        db, client, order_id=order_id, settings=settings, waxpeer=waxpeer
                    )
                else:
                    await check_purchase(db, client, order_id=order_id, settings=settings)
        except Exception as exc:  # noqa: BLE001 -- one order must not stop the tick
            log.error("orders.skinslink.reconcile_failed", error=type(exc).__name__)  # noqa: TRY400
    return len(due)


__all__ = ["POLL_EVERY", "reconcile_skinslink"]
