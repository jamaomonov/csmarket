"""The sales poll (spec 2026-10-08 §6): the fallback for the webhooks Skinslink never sends.

No webhook comes before ``hold``, so ``creating`` and ``offered`` sales are asked about every
:data:`OPEN_POLL_EVERY`; a ``hold`` sale every :data:`HOLD_POLL_EVERY`, in case its webhook
was lost. A sale closed ``not_created`` (``create-deposit`` never answered, Skinslink did not
know it) is asked every :data:`LATE_POLL_EVERY` for :data:`LATE_WINDOW`: a slow call may still
have sent the offer, and a late deposit is then reopened and paid (review SB-1). Each sale is
checked in its own session (``status.check_sale``): one failure never stops the tick.

The same tick exports the gauges the alerts read: card payouts waiting past
:data:`OVERDUE_AFTER`, open attentions by reason, and sales still in ``hold``
:data:`HOLD_OVERDUE_AFTER` past their hold end (a status read that keeps failing, SB-7).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta

from sqlalchemy import ColumnElement, and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.clock import now
from csmarket.core.logging import get_logger
from csmarket.core.metrics import (
    SaleAttentionReason,
    set_sale_attention_open,
    set_sale_holds_overdue,
    set_sale_payouts_overdue,
)
from csmarket.modules.sales.models import PayoutRequest, Sale
from csmarket.modules.sales.status import check_sale
from csmarket.modules.skinslink.api import DepositClient

log = get_logger("csmarket.sales.reconcile")

OPEN_POLL_EVERY = timedelta(seconds=60)
HOLD_POLL_EVERY = timedelta(minutes=30)
OVERDUE_AFTER = timedelta(hours=48)
#: How long after its hold end a ``hold`` sale counts as stuck.
HOLD_OVERDUE_AFTER = timedelta(hours=6)
#: A ``not_created`` sale is asked about this often ...
LATE_POLL_EVERY = timedelta(minutes=5)
#: ... for this long after it was created.
LATE_WINDOW = timedelta(hours=24)
_REASONS: tuple[SaleAttentionReason, ...] = ("rolled_back", "late_deposit", "credit_blocked")
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
                and_(
                    Sale.status == "closed",
                    Sale.fail_reason == "not_created",
                    Sale.created_at >= at - LATE_WINDOW,
                    _due_since(LATE_POLL_EVERY, at),
                ),
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


async def holds_overdue(db: AsyncSession, *, at: datetime) -> int:
    """Sales in ``hold`` more than :data:`HOLD_OVERDUE_AFTER` past their hold end."""
    count = await db.scalar(
        select(func.count())
        .select_from(Sale)
        .where(Sale.status == "hold", Sale.hold_end_at <= at - HOLD_OVERDUE_AFTER)
    )
    return int(count or 0)


async def attention_open(db: AsyncSession) -> dict[SaleAttentionReason, int]:
    """Open (unresolved) sale attentions by reason; every reason present, 0 if none."""
    rows = await db.execute(
        select(Sale.attention_reason, func.count())
        .where(Sale.attention_reason.is_not(None), Sale.resolved_at.is_(None))
        .group_by(Sale.attention_reason)
    )
    found = {str(reason): int(n) for reason, n in rows.all()}
    return {reason: found.get(reason, 0) for reason in _REASONS}


async def _export(db: AsyncSession, at: datetime) -> None:
    """Set the gauges the sales alerts read."""
    set_sale_payouts_overdue(await payouts_overdue(db, at=at))
    set_sale_holds_overdue(await holds_overdue(db, at=at))
    for reason, count in (await attention_open(db)).items():
        set_sale_attention_open(reason, count)


async def poll_sales(
    db_factory: SessionFactory, client: DepositClient, *, at: datetime | None = None
) -> int:
    """One tick: ask about every due sale; export the gauges.

    Returns:
        How many sales the tick asked about.
    """
    moment = at or now()
    async with db_factory() as db:
        due = await _due(db, moment)
        await _export(db, moment)
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
    "HOLD_OVERDUE_AFTER",
    "HOLD_POLL_EVERY",
    "LATE_POLL_EVERY",
    "LATE_WINDOW",
    "OPEN_POLL_EVERY",
    "OVERDUE_AFTER",
    "attention_open",
    "holds_overdue",
    "payouts_overdue",
    "poll_sales",
]
