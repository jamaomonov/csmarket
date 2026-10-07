"""The worker buys a paid Skinslink order — at most once (spec 2026-10-06 §6).

:func:`attempt_skinslink_buy` mirrors ``orders.buying.attempt_buy``:

1. take the order's lease (``take_lease(..., source="skinslink")``), then read the snapshot;
2. a trade link that does not parse → refund ``invalid_trade_link``;
3. ``POST /merchant/purchase`` keyed by our ``merchant_tx_id`` (the order id) with
   ``max_price`` = the agreed cost: Skinslink answers a repeat with the stored purchase, so a
   lost answer is resolved by asking again under the same id (Task 9's reconcile), never by
   a new purchase;
4. a refusal (sold, price moved, a 4xx) → refund ``sold_out``, never another offer
   (ADR-0013); low balance → refund; a refusal naming the trade link → refund ``invalid_trade_link``;
   403 → attention, the buy kept pending; 429 → retried after a backoff; no answer →
   ``buy_unconfirmed_at``.

No lock is held across a Skinslink call (``orders.skinslink_writes``). Log lines carry the
order number and the outcome, never the trade link.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from decimal import Decimal
from typing import cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.errors import ValidationError
from csmarket.core.logging import get_logger
from csmarket.core.metrics import OrderBuyOutcome, record_order_buy
from csmarket.modules.orders.buy_lease import BUY_LEASE, discard, release, release_fresh, take_lease
from csmarket.modules.orders.models import Order
from csmarket.modules.orders.skinslink_writes import (
    PurchaseSnapshot,
    attention,
    record_purchase,
    refund,
    secure_sent,
    unconfirmed,
)
from csmarket.modules.skinslink.api import (
    LINK_ERROR_CODES,
    Purchase,
    SkinslinkError,
    SkinslinkForbiddenError,
    SkinslinkPurchase,
    SkinslinkPurchaseClient,
    SkinslinkRateLimitedError,
    SkinslinkUnavailableError,
)
from csmarket.modules.users.api import TradeLink, parse_tradelink

log = get_logger("csmarket.orders.skinslink_buying")

#: An attempt's time budget, counted from before its lease is taken.
ATTEMPT_BUDGET = BUY_LEASE - timedelta(seconds=30)
#: How long the order waits after a 403 or a 429 before the next attempt.
RELEASE_BACKOFF: dict[str, timedelta] = {
    "forbidden": timedelta(seconds=60),
    "rate_limited": timedelta(seconds=20),
}
_UNCOUNTED = frozenset({"nothing_to_do", "lookup_later"})
_SECURE_SECONDS = 10.0
_UNITS_PER_USD = Decimal(1000)
#: Purchase statuses that mean Skinslink took the purchase.
_TAKEN = frozenset({"new", "pending", "active", "hold", "completed"})


class _Run:
    """One attempt's progress: its snapshot once read, whether a request went out."""

    __slots__ = ("sent", "snap")

    def __init__(self) -> None:
        self.snap: PurchaseSnapshot | None = None
        self.sent = False


async def attempt_skinslink_buy(
    db: AsyncSession,
    client: SkinslinkPurchaseClient,
    *,
    order_id: str,
) -> str:
    """Buy order ``order_id`` at Skinslink, unless it was bought or is being bought.

    Args:
        db: Session; each step commits its own short transaction.
        client: Skinslink.
        order_id: The order.

    Returns:
        ``bought``, ``adopted``, ``sold_out``, ``low_balance``, ``invalid_link``,
        ``forbidden``, ``rate_limited``, ``unconfirmed``, ``stale_bought``, ``unrecorded``,
        ``lookup_later`` (nothing sent before the budget ran out) or ``nothing_to_do``.
    """
    deadline = asyncio.get_running_loop().time() + ATTEMPT_BUDGET.total_seconds()
    lease = await take_lease(db, order_id, source="skinslink")
    if lease is None:
        return "nothing_to_do"
    run = _Run()
    try:
        async with asyncio.timeout_at(deadline):
            outcome = await _leased(db, client, order_id=order_id, run=run)
    except TimeoutError:
        outcome = await _after_timeout(db, order_id=order_id, lease=lease, run=run)
    except BaseException:
        if run.sent and run.snap is not None:
            await discard(db)
            await _secure(db, run.snap)
        raise
    else:
        await release(db, order_id, lease, after=RELEASE_BACKOFF.get(outcome, timedelta(0)))
    if run.snap is None:
        return outcome
    if outcome not in _UNCOUNTED:
        record_order_buy(cast(OrderBuyOutcome, outcome))  # every other outcome is in the set
    log.info("orders.skinslink_buy", number=run.snap.number, outcome=outcome)
    return outcome


async def _secure(db: AsyncSession, snap: PurchaseSnapshot) -> bool | None:
    """Record a sent purchase as unconfirmed through a fresh session; ``None`` on failure."""
    try:
        async with (
            asyncio.timeout(_SECURE_SECONDS),
            AsyncSession(bind=db.bind, expire_on_commit=False) as fresh,
        ):
            return await secure_sent(fresh, snap)
    except Exception as exc:  # noqa: BLE001 -- keep the lease; the error is logged
        log.error("orders.skinslink_buy.unrecorded", number=snap.number, error=type(exc).__name__)  # noqa: TRY400
        return None


async def _after_timeout(db: AsyncSession, *, order_id: str, lease: datetime, run: _Run) -> str:
    """The budget ran out: nothing sent → due again; a sent purchase → unconfirmed."""
    await discard(db)
    if not run.sent or run.snap is None:
        await release_fresh(db, order_id, lease)
        return "lookup_later"
    marked = await _secure(db, run.snap)
    if marked is None:
        return "unrecorded"
    await release_fresh(db, order_id, lease)
    return "unconfirmed" if marked else "nothing_to_do"


async def _leased(
    db: AsyncSession,
    client: SkinslinkPurchaseClient,
    *,
    order_id: str,
    run: _Run,
) -> str:
    """Read the snapshot under the lease, then buy."""
    order = await db.scalar(
        select(Order).where(Order.id == order_id).execution_options(populate_existing=True)
    )
    purchase = await db.scalar(
        select(SkinslinkPurchase)
        .where(SkinslinkPurchase.order_id == order_id)
        .execution_options(populate_existing=True)
    )
    await db.commit()
    if order is None or purchase is None or order.status != "buying" or not purchase.buy_pending:
        return "nothing_to_do"
    run.snap = PurchaseSnapshot(
        order_id=order.id,
        number=order.number,
        skin_item_id=order.skin_item_id,
        merchant_tx_id=purchase.merchant_tx_id,
        asset_id=purchase.asset_id,
        paid_units=purchase.paid_units,
        cost_units=order.cost_units,
    )
    try:
        link = parse_tradelink(order.trade_link)
    except ValidationError:
        return await refund(db, run.snap, "invalid_trade_link")
    settled = await _purchase_once(db, client, run.snap, link, run)
    if settled is not None:
        return settled
    log.info("orders.skinslink_buy.refused", number=run.snap.number)
    return await refund(db, run.snap, "sold_out")  # never another offer (ADR-0013)


async def _purchase_once(  # noqa: PLR0911 -- one return per outcome reads as the table
    db: AsyncSession,
    client: SkinslinkPurchaseClient,
    snap: PurchaseSnapshot,
    link: TradeLink,
    run: _Run,
) -> str | None:
    """One purchase request: the attempt's outcome, or ``None`` for a refused offer."""
    try:
        run.sent = True  # from here on an unrecorded exit must not free the order
        report = await client.purchase(
            asset_id=snap.asset_id,
            partner=link.partner,
            token=link.token,
            merchant_tx_id=snap.merchant_tx_id,
            max_price_usd=Decimal(snap.paid_units) / _UNITS_PER_USD,
        )
    except SkinslinkForbiddenError:
        return await attention(db, snap, "source_forbidden", outcome="forbidden")
    except SkinslinkRateLimitedError:
        return "rate_limited"
    except SkinslinkUnavailableError:
        return await unconfirmed(db, snap)  # it may have gone through: ask again later
    except SkinslinkError as err:
        if err.code in LINK_ERROR_CODES:
            return await refund(db, snap, "invalid_trade_link")
        if err.status == 409 or err.code == "duplicate_purchase":
            return await _adopt(db, client, snap)
        if err.code == "insufficient_balance":
            return await refund(db, snap, "source_low_balance")
        return None
    if report.status in _TAKEN:
        return await record_purchase(db, snap, report)
    if report.fail_reason == "insufficient_balance":
        return await refund(db, snap, "source_low_balance")
    if report.fail_reason == "duplicate_purchase":
        return await _adopt(db, client, snap)
    return None


async def _adopt(
    db: AsyncSession, client: SkinslinkPurchaseClient, snap: PurchaseSnapshot
) -> str | None:
    """A repeat of ``merchant_tx_id``: take the stored purchase; a failed one was refused."""
    try:
        report: Purchase | None = await client.purchase_status(merchant_tx_id=snap.merchant_tx_id)
    except (SkinslinkError, SkinslinkUnavailableError):
        report = None
    if report is None:
        return await unconfirmed(db, snap)  # the reconcile asks again
    if report.status not in _TAKEN:
        return None
    return await record_purchase(db, snap, report, outcome="adopted")


__all__ = ["ATTEMPT_BUDGET", "RELEASE_BACKOFF", "attempt_skinslink_buy"]
