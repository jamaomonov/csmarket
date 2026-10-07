"""The LIS-SKINS reconcile (spec 2026-10-07 §6): statuses are polled; there is no webhook.

Every 30 s (``lisskins.reconcile``): a LIS-SKINS order whose buy is pending is bought
(``lisskins_buying``; its lease decides whether anyone else is on it); every other open one —
and a delivered one inside Steam's trade protection, where a rollback can still come — is
asked about in **one** ``GET /market/info`` call by our ``custom_id`` (≤ 200, open ones
first). A purchase LIS-SKINS does not show, whose buy's answer was lost, is bought again
under the same ``custom_id`` once ``order_unconfirmed_minutes`` passed: a second purchase is
impossible, LIS-SKINS refuses a known ``custom_id``. A purchase we hold an id for is never
settled by its absence. Each order gets its own session; one failure never stops the tick.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.clock import now
from csmarket.core.config import Settings
from csmarket.core.logging import get_logger
from csmarket.modules.lisskins.api import (
    INFO_MAX_IDS,
    LisskinsBuyClient,
    LisskinsError,
    LisskinsPurchase,
    LisskinsUnavailableError,
    Purchase,
)
from csmarket.modules.orders.lisskins_buying import attempt_lisskins_buy
from csmarket.modules.orders.lisskins_status import apply_report, lock
from csmarket.modules.orders.models import Order

log = get_logger("csmarket.orders.lisskins_reconcile")

#: Steam's trade protection (7 days) and a margin: an accepted trade can be rolled back.
PROTECTION = timedelta(days=8)
#: How often a delivered order inside :data:`PROTECTION` is asked about.
PROTECTION_POLL_EVERY = timedelta(minutes=10)
#: Pending buys per tick.
BUY_BATCH = 20

SessionFactory = Callable[[], AsyncSession]


async def _pending(db: AsyncSession) -> list[str]:
    """Orders whose buy is due (the lease decides who takes it)."""
    rows = await db.scalars(
        select(LisskinsPurchase.order_id)
        .join(Order, Order.id == LisskinsPurchase.order_id)
        .where(Order.status == "buying", LisskinsPurchase.buy_pending.is_(True))
        .order_by(Order.created_at)
        .limit(BUY_BATCH)
    )
    return list(rows.all())


async def _to_poll(db: AsyncSession) -> dict[str, str]:
    """``custom_id → order id`` of the purchases to ask about: open ones first, then those
    in trade protection, each longest-unpolled first."""
    at = now()
    open_ = and_(
        Order.status.in_(("buying", "trade_sent")),
        LisskinsPurchase.buy_pending.is_(False),
        # A rollback before ``accepted`` is LIS-SKINS' last word and waits for an admin.
        or_(
            LisskinsPurchase.status.is_distinct_from("return"),
            LisskinsPurchase.attention_reason.is_distinct_from("rolled_back"),
        ),
    )
    protected = and_(
        Order.status == "delivered",
        LisskinsPurchase.status == "accepted",
        Order.delivered_at > at - PROTECTION,
        or_(
            LisskinsPurchase.last_polled_at.is_(None),
            LisskinsPurchase.last_polled_at <= at - PROTECTION_POLL_EVERY,
        ),
    )
    rows = await db.execute(
        select(LisskinsPurchase.custom_id, LisskinsPurchase.order_id)
        .join(Order, Order.id == LisskinsPurchase.order_id)
        .where(or_(open_, protected))
        .order_by(
            Order.status == "delivered",
            LisskinsPurchase.last_polled_at.asc().nulls_first(),
            Order.created_at,
        )
        .limit(INFO_MAX_IDS)
    )
    return {custom_id: order_id for custom_id, order_id in rows.all()}


def _settle_unseen(order: Order, purchase: LisskinsPurchase, settings: Settings) -> str:
    """LIS-SKINS shows nothing under our ``custom_id``. A lost buy past the wait is due
    again under the same id (spec §6), its ``buy_unconfirmed_at`` kept as the mark of a
    repeat; one an admin was asked about (``buy_unconfirmed``) waits until it is resolved."""
    purchase.last_polled_at = now()
    unseen = purchase.buy_unconfirmed_at
    if (
        unseen is None
        or purchase.purchase_id is not None
        or order.status != "buying"
        or purchase.buy_pending
        or (purchase.attention_reason == "buy_unconfirmed" and purchase.resolved_at is None)
    ):
        return "unchanged"
    if now() - unseen < timedelta(minutes=settings.order_unconfirmed_minutes):
        return "unchanged"
    purchase.buy_pending = True
    order.next_check_at = None  # due for the next tick's buy at once
    log.warning("orders.lisskins.repeat_unseen", number=order.number)
    return "repeat"


async def apply_polled(
    db: AsyncSession,
    *,
    order_id: str,
    custom_id: str,
    report: Purchase | None,
    settings: Settings,
) -> str:
    """Apply one polled answer under the locks; commits.

    ``report`` ``None``: LIS-SKINS holds no purchase under ``custom_id``. A row that went
    pending during the call is left alone.
    """
    pair = await lock(db, order_id)
    if pair is None or pair[1].buy_pending or pair[1].custom_id != custom_id:
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
        log.info("orders.lisskins.polled", number=order.number, outcome=outcome)
    return outcome


async def _poll(
    db_factory: SessionFactory,
    client: LisskinsBuyClient,
    due: dict[str, str],
    *,
    settings: Settings,
) -> None:
    try:
        reports = await client.info(custom_ids=list(due))
    except (LisskinsError, LisskinsUnavailableError) as exc:
        log.warning("orders.lisskins.info_failed", error=type(exc).__name__)
        return
    found = {p.custom_id: p for p in reports if p.custom_id is not None}
    for custom_id, order_id in due.items():
        try:
            async with db_factory() as db:
                await apply_polled(
                    db,
                    order_id=order_id,
                    custom_id=custom_id,
                    report=found.get(custom_id),
                    settings=settings,
                )
        except Exception as exc:  # noqa: BLE001 -- one order must not stop the tick
            log.error("orders.lisskins.poll_failed", error=type(exc).__name__)  # noqa: TRY400


async def reconcile_lisskins(
    db_factory: SessionFactory,
    client: LisskinsBuyClient,
    *,
    settings: Settings,
) -> int:
    """One tick: buy the due buys, then poll everything else in one call.

    Returns:
        How many orders the tick looked at.
    """
    async with db_factory() as db:
        pending = await _pending(db)
        due = await _to_poll(db)
        await db.commit()
    for order_id in pending:
        try:
            async with db_factory() as db:
                await attempt_lisskins_buy(db, client, order_id=order_id)
        except Exception as exc:  # noqa: BLE001 -- one order must not stop the tick
            log.error("orders.lisskins.reconcile_failed", error=type(exc).__name__)  # noqa: TRY400
    if due:
        await _poll(db_factory, client, due, settings=settings)
    return len(pending) + len(due)


__all__ = [
    "BUY_BATCH",
    "PROTECTION",
    "PROTECTION_POLL_EVERY",
    "apply_polled",
    "reconcile_lisskins",
]
