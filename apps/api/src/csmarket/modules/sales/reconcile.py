"""The sales poll (spec 2026-10-08 §6): the fallback for the webhooks Skinslink never sends.

No webhook comes before ``hold``, so ``creating`` and ``offered`` sales are asked about every
:data:`OPEN_POLL_EVERY`; a ``hold`` sale every :data:`HOLD_POLL_EVERY`, in case its webhook
was lost. Each sale is checked in its own session (``status.check_sale``): one failure never
stops the tick. The same tick exports how many card payouts wait past :data:`OVERDUE_AFTER`.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta

from sqlalchemy import ColumnElement, and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.clock import now
from csmarket.core.logging import get_logger
from csmarket.core.metrics import set_sale_payouts_overdue
from csmarket.modules.sales.models import PayoutRequest, Sale
from csmarket.modules.sales.status import check_sale
from csmarket.modules.skinslink.api import DepositClient

log = get_logger("csmarket.sales.reconcile")

OPEN_POLL_EVERY = timedelta(seconds=60)
HOLD_POLL_EVERY = timedelta(minutes=30)
OVERDUE_AFTER = timedelta(hours=48)
#: Sales per tick.
BATCH = 50

SessionFactory = Callable[[], AsyncSession]


def _due_since(every: timedelta, at: datetime) -> ColumnElement[bool]:
    """Never polled, or last polled ``every`` ago or longer."""
    return or_(Sale.last_polled_at.is_(None), Sale.last_polled_at <= at - every)


async def _due(db: AsyncSession, at: datetime) -> list[str]:
    """Ids of the open sales due a poll, least recently polled first."""
    rows = await db.scalars(
        select(Sale.id)
        .where(
            or_(
                and_(Sale.status.in_(("creating", "offered")), _due_since(OPEN_POLL_EVERY, at)),
                and_(Sale.status == "hold", _due_since(HOLD_POLL_EVERY, at)),
            )
        )
        .order_by(Sale.last_polled_at.asc().nulls_first(), Sale.created_at)
        .limit(BATCH)
    )
    return [str(x) for x in rows.all()]


async def payouts_overdue(db: AsyncSession, *, at: datetime) -> int:
    """Card payouts ``to_pay`` for longer than :data:`OVERDUE_AFTER`."""
    count = await db.scalar(
        select(func.count())
        .select_from(PayoutRequest)
        .where(PayoutRequest.status == "to_pay", PayoutRequest.to_pay_at <= at - OVERDUE_AFTER)
    )
    return int(count or 0)


async def poll_sales(
    db_factory: SessionFactory, client: DepositClient, *, at: datetime | None = None
) -> int:
    """One tick: ask about every due open sale; export the overdue payouts.

    Returns:
        How many sales the tick asked about.
    """
    moment = at or now()
    async with db_factory() as db:
        due = await _due(db, moment)
        set_sale_payouts_overdue(await payouts_overdue(db, at=moment))
        await db.commit()
    for sale_id in due:
        try:
            async with db_factory() as db:
                await check_sale(db, client, sale_id=sale_id)
        except Exception as exc:  # noqa: BLE001 -- one sale must not stop the tick
            log.error("sales.poll_failed", error=type(exc).__name__)  # noqa: TRY400
    return len(due)


__all__ = [
    "BATCH",
    "HOLD_POLL_EVERY",
    "OPEN_POLL_EVERY",
    "OVERDUE_AFTER",
    "payouts_overdue",
    "poll_sales",
]
