"""The trade sweeps the scheduler times (rulings R3, R5; ``csmarket_scheduler.jobs``).

- :func:`reconcile` (every ``trades_reconcile_seconds``): the due ``buying`` / ``trade_sent``
  orders. Those whose trade is polled are looked up in one ``check-many-project-id`` call and
  moved by :func:`.trades.apply`; a buy still ``buy_pending`` goes to
  :func:`.buying.attempt_buy`, whose lease is the only writer of its ``next_check_at``.
- :func:`watch_protected` (hourly): delivered trades in Steam's protection — a rollback is
  money spent (attention ``rolled_back``, never a refund, R3).
- :func:`expire_pending` (every minute, ``orders.expiry``) and :func:`audit_recent` (daily,
  ``orders.trade_audit``) are re-exported here: the scheduler's jobs import this module.

No lock is held across a Waxpeer call: rows are read, the transaction ends, Waxpeer is
asked, then each order is locked, then its trade (ruling K), re-checked and written in its
own transaction. Log lines carry the order number, never the buyer or a Waxpeer URL.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.clock import now
from csmarket.core.config import Settings
from csmarket.core.logging import get_logger
from csmarket.modules.orders.buying import attempt_buy
from csmarket.modules.orders.expiry import expire_pending
from csmarket.modules.orders.models import Order, SkinTrade
from csmarket.modules.orders.sweep_base import (
    LOOKUP_ERRORS,
    SweepRow,
    crashed,
    lock_both,
    lookup,
    of_project,
)
from csmarket.modules.orders.trade_audit import AUDIT_DAYS, audit_recent
from csmarket.modules.orders.trades import (
    SENT_STATUS,
    AmbiguousTradeError,
    apply,
    flag,
    pick_trade,
)
from csmarket.modules.skins.api import LOOKUP_MAX_IDS, TradeClient, WaxpeerTrade

log = get_logger("csmarket.orders.sweeps")

#: Orders one reconcile tick looks at (one lookup call).
RECONCILE_BATCH = LOOKUP_MAX_IDS
#: Statuses the reconcile sweep follows.
RECONCILED = ("buying", "trade_sent")

SessionFactory = Callable[[], AsyncSession]


# --- reconcile -----------------------------------------------------------------------------


async def _due(db: AsyncSession) -> list[SweepRow]:
    """The oldest due orders the sweep follows; ends the read transaction."""
    rows = await db.execute(
        select(Order.id, SkinTrade.project_id, SkinTrade.buy_pending)
        .join(SkinTrade, SkinTrade.order_id == Order.id)
        .where(
            Order.status.in_(RECONCILED),
            or_(Order.next_check_at.is_(None), Order.next_check_at <= now()),
        )
        .order_by(Order.next_check_at.asc().nulls_first(), Order.created_at)
        .limit(RECONCILE_BATCH)
    )
    due = [SweepRow(order_id=r[0], project_id=r[1], buy_pending=r[2]) for r in rows.all()]
    await db.commit()
    return due


def _unseen(order: Order, trade: SkinTrade, settings: Settings) -> str:
    """No trade under our ``project_id``: a lost buy answer waits, then needs an admin (R3)."""
    since = trade.buy_unconfirmed_at
    window = timedelta(minutes=settings.order_unconfirmed_minutes)
    if since is None or now() - since <= window:
        return "unseen"
    if flag(trade, "buy_unconfirmed"):
        log.error("orders.trade.buy_unconfirmed", number=order.number)
    return "unconfirmed"


async def _reconcile_one(
    db: AsyncSession, row: SweepRow, theirs: list[WaxpeerTrade], *, settings: Settings
) -> str:
    """Lock order → trade, re-check, apply what Waxpeer reported, schedule the next look."""
    order, trade = await lock_both(db, row.order_id)
    if (
        order is None
        or trade is None
        or order.status not in RECONCILED
        or trade.buy_pending  # the buy's own lease decides its next look (ruling M)
        or (order.next_check_at is not None and order.next_check_at > now())
    ):
        await db.commit()
        return "skipped"
    try:
        wt = pick_trade(theirs, trade.waxpeer_id)
    except AmbiguousTradeError:
        if flag(trade, "ambiguous_trade"):
            # An event, not a traceback: the attention is the record an admin works from.
            log.error("orders.trade.ambiguous", number=order.number, trades=len(theirs))  # noqa: TRY400
        outcome = "ambiguous"
    else:
        if wt is None:
            outcome = _unseen(order, trade, settings)
        else:
            outcome = await apply(db, order=order, trade=trade, wt=wt)
    if order.status in RECONCILED:
        order.next_check_at = now() + timedelta(seconds=settings.trades_reconcile_seconds)
    await db.commit()
    if outcome not in ("unchanged", "unseen"):
        log.info("orders.trade", number=order.number, outcome=outcome)
    return outcome


async def _poll(
    db: AsyncSession, client: TradeClient, rows: list[SweepRow], *, settings: Settings
) -> None:
    """One lookup for ``rows``, then each order in its own transaction."""
    try:
        found = await lookup(client, [r.project_id for r in rows])
    except LOOKUP_ERRORS as exc:
        # Every row stays due: the next tick asks again.
        log.warning("orders.reconcile.lookup_failed", error=type(exc).__name__, orders=len(rows))
        return
    for row in rows:
        try:
            await _reconcile_one(db, row, of_project(found, row.project_id), settings=settings)
        except Exception as exc:  # noqa: BLE001 -- one bad order must not stop the sweep
            await db.rollback()
            crashed("orders.reconcile.crashed", row.order_id, exc)


async def reconcile(db_factory: SessionFactory, client: TradeClient, *, settings: Settings) -> int:
    """One reconcile tick over at most :data:`RECONCILE_BATCH` due orders. Never raises.

    Polled orders first (one lookup), then the buys still pending, each through
    :func:`.buying.attempt_buy` (which takes the order's lease or does nothing).

    Args:
        db_factory: Opens the sweep's session.
        client: Waxpeer.
        settings: ``trades_reconcile_seconds``, ``order_unconfirmed_minutes`` and the buy's.

    Returns:
        How many due orders the tick looked at (0 when it failed before reading any).
    """
    try:
        async with db_factory() as db:
            due = await _due(db)
            polled = [r for r in due if not r.buy_pending]
            if polled:
                await _poll(db, client, polled, settings=settings)
            for row in (r for r in due if r.buy_pending):
                try:
                    await attempt_buy(db, client, order_id=row.order_id, settings=settings)
                except Exception as exc:  # noqa: BLE001 -- the next tick retries this buy
                    await db.rollback()
                    crashed("orders.reconcile.buy_crashed", row.order_id, exc)
    except Exception as exc:  # noqa: BLE001 -- a sweep never raises; the next tick retries
        log.error("orders.reconcile.failed", error=type(exc).__name__)  # noqa: TRY400
        return 0
    return len(due)


# --- protection watch ----------------------------------------------------------------------


async def _watch_one(db: AsyncSession, row: SweepRow, theirs: list[WaxpeerTrade]) -> str:
    """Lock order → trade, re-check it is still in protection, apply Waxpeer's report."""
    order, trade = await lock_both(db, row.order_id)
    outcome = "skipped"
    if (
        order is not None
        and trade is not None
        and order.status == "delivered"
        and trade.status == SENT_STATUS
        and not trade.is_released
    ):
        try:
            wt = pick_trade(theirs, trade.waxpeer_id)
        except AmbiguousTradeError:
            # Nothing is mirrored from a guess; the audit reports it.
            log.warning("orders.protection.ambiguous", number=order.number)
            wt = None
        if wt is not None:
            outcome = await apply(db, order=order, trade=trade, wt=wt)
    await db.commit()
    return outcome


async def watch_protected(db: AsyncSession, client: TradeClient) -> int:
    """Follow delivered trades through Steam's protection; a rollback needs an admin (R3).

    Released (5) is mirrored; a rollback (6) is money spent: attention ``rolled_back`` and
    the metric, the order stays ``delivered``. A lookup failure ends the run (the next one
    retries).

    Args:
        db: Session; each order is written and committed in its own transaction.
        client: Waxpeer.

    Returns:
        How many trades were in protection.
    """
    rows = [
        SweepRow(order_id=r[0], project_id=r[1])
        for r in (
            await db.execute(
                select(Order.id, SkinTrade.project_id)
                .join(SkinTrade, SkinTrade.order_id == Order.id)
                .where(
                    Order.status == "delivered",
                    SkinTrade.status == SENT_STATUS,
                    SkinTrade.release_date.is_not(None),
                    SkinTrade.is_released.is_(False),
                )
                .order_by(SkinTrade.created_at, SkinTrade.order_id)
            )
        ).all()
    ]
    await db.commit()
    for start in range(0, len(rows), LOOKUP_MAX_IDS):
        chunk = rows[start : start + LOOKUP_MAX_IDS]
        try:
            found = await lookup(client, [r.project_id for r in chunk])
        except LOOKUP_ERRORS as exc:
            log.warning("orders.protection.lookup_failed", error=type(exc).__name__)
            break
        for row in chunk:
            try:
                await _watch_one(db, row, of_project(found, row.project_id))
            except Exception as exc:  # noqa: BLE001 -- one bad order must not stop the watch
                await db.rollback()
                crashed("orders.protection.crashed", row.order_id, exc)
    return len(rows)


__all__ = [
    "AUDIT_DAYS",
    "RECONCILED",
    "RECONCILE_BATCH",
    "audit_recent",
    "expire_pending",
    "reconcile",
    "watch_protected",
]
