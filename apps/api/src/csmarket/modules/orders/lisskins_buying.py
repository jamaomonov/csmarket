"""The worker buys a paid LIS-SKINS order — at most once (spec 2026-10-07 §5).

:func:`attempt_lisskins_buy` has the Skinslink path's shape (``orders.skinslink_buying``):

1. take the order's lease (``take_lease(..., source="lisskins")``), then read the snapshot;
2. a trade link that does not parse → refund ``invalid_trade_link``;
3. ``POST /market/buy`` for the one lot, keyed by our ``custom_id`` (the order id), with
   ``max_price`` = the agreed cost. LIS-SKINS refuses a ``custom_id`` it knows, so a repeat
   never buys twice: ``custom_id_already_exists`` is answered from ``market/info`` and the
   stored purchase adopted;
4. sold or dearer than our cap → refund ``sold_out``, never another lot (ADR-0013) — except
   on a repeat of a lost buy, whose refusal of the lot may be our own first purchase:
   ``market/info`` decides, else the ``buy_unconfirmed`` attention
   (``lisskins_writes.held``); ``insufficient_funds`` → refund
   ``source_low_balance``; a refusal naming the trade link → refund ``invalid_trade_link``;
   401/403 → attention ``source_forbidden``, the buy kept pending; 429 → retried after its
   ``Retry-After``; no answer, a timeout or a 5xx → ``buy_unconfirmed_at``, settled by the
   reconcile's ``market/info`` (``orders.lisskins_reconcile``).

No lock is held across a LIS-SKINS call (``orders.lisskins_writes``). Log lines carry the
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
from csmarket.core.redis import get_redis
from csmarket.modules.lisskins.api import (
    BUY_LINK_ERRORS,
    BUY_SOLD_ERRORS,
    LisskinsBuyClient,
    LisskinsError,
    LisskinsForbiddenError,
    LisskinsPurchase,
    LisskinsRateLimitedError,
    LisskinsUnavailableError,
    remember_rejection,
)
from csmarket.modules.orders.buy_lease import BUY_LEASE, discard, release, release_fresh, take_lease
from csmarket.modules.orders.lisskins_writes import (
    LisskinsSnapshot,
    attention,
    held,
    record_purchase,
    refund,
    secure_sent,
    unconfirmed,
)
from csmarket.modules.orders.models import Order
from csmarket.modules.users.api import TradeLink, parse_tradelink

log = get_logger("csmarket.orders.lisskins_buying")

#: An attempt's time budget, counted from before its lease is taken.
ATTEMPT_BUDGET = BUY_LEASE - timedelta(seconds=30)
#: How long the order waits after a 401/403 or a 429 before the next attempt.
RELEASE_BACKOFF: dict[str, timedelta] = {
    "forbidden": timedelta(seconds=60),
    "rate_limited": timedelta(seconds=20),
}
#: The longest a 429's own ``Retry-After`` may hold an order.
MAX_RETRY_AFTER = BUY_LEASE
_UNCOUNTED = frozenset({"nothing_to_do", "lookup_later"})
_SECURE_SECONDS = 10.0
_UNITS_PER_USD = Decimal(1000)
#: Refusals about the buyer or our balance, never about the lot: a repeat settles them as a
#: first buy would.
_MOVED_ON = frozenset({*BUY_LINK_ERRORS, "insufficient_funds"})


class _Run:
    """One attempt's progress: its snapshot, whether a request went out, a 429's wait."""

    __slots__ = ("refusal", "retry_after", "sent", "snap")

    def __init__(self) -> None:
        self.snap: LisskinsSnapshot | None = None
        self.sent = False
        self.retry_after: float | None = None
        #: LIS-SKINS' refusal code of a lot it would not sell.
        self.refusal: str | None = None

    def backoff(self, outcome: str) -> timedelta:
        """:data:`RELEASE_BACKOFF`, or LIS-SKINS' own ``Retry-After`` when longer (capped)."""
        wait = RELEASE_BACKOFF.get(outcome, timedelta(0))
        if self.retry_after is not None and wait > timedelta(0):
            wait = max(wait, min(timedelta(seconds=self.retry_after), MAX_RETRY_AFTER))
        return wait


async def attempt_lisskins_buy(
    db: AsyncSession,
    client: LisskinsBuyClient,
    *,
    order_id: str,
) -> str:
    """Buy order ``order_id`` at LIS-SKINS, unless it was bought or is being bought.

    Args:
        db: Session; each step commits its own short transaction.
        client: LIS-SKINS (the buy timeout).
        order_id: The order.

    Returns:
        ``bought``, ``adopted``, ``sold_out``, ``low_balance``, ``invalid_link``,
        ``forbidden``, ``rate_limited``, ``unconfirmed``, ``stale_bought``, ``unrecorded``,
        ``lookup_later`` (nothing sent before the budget ran out) or ``nothing_to_do``.
    """
    deadline = asyncio.get_running_loop().time() + ATTEMPT_BUDGET.total_seconds()
    lease = await take_lease(db, order_id, source="lisskins")
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
        await release(db, order_id, lease, after=run.backoff(outcome))
    if run.snap is None:
        return outcome
    if outcome not in _UNCOUNTED:
        record_order_buy(cast(OrderBuyOutcome, outcome))  # every other outcome is in the set
    log.info("orders.lisskins_buy", number=run.snap.number, outcome=outcome)
    return outcome


async def _secure(db: AsyncSession, snap: LisskinsSnapshot) -> bool | None:
    """Record a sent buy as unconfirmed through a fresh session; ``None`` on failure."""
    try:
        async with (
            asyncio.timeout(_SECURE_SECONDS),
            AsyncSession(bind=db.bind, expire_on_commit=False) as fresh,
        ):
            return await secure_sent(fresh, snap)
    except Exception as exc:  # noqa: BLE001 -- keep the lease; the error is logged
        log.error("orders.lisskins_buy.unrecorded", number=snap.number, error=type(exc).__name__)  # noqa: TRY400
        return None


async def _after_timeout(db: AsyncSession, *, order_id: str, lease: datetime, run: _Run) -> str:
    """The budget ran out: nothing sent → due again; a sent buy → unconfirmed."""
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
    client: LisskinsBuyClient,
    *,
    order_id: str,
    run: _Run,
) -> str:
    """Read the snapshot under the lease, then buy."""
    order = await db.scalar(
        select(Order).where(Order.id == order_id).execution_options(populate_existing=True)
    )
    purchase = await db.scalar(
        select(LisskinsPurchase)
        .where(LisskinsPurchase.order_id == order_id)
        .execution_options(populate_existing=True)
    )
    await db.commit()
    if order is None or purchase is None or order.status != "buying" or not purchase.buy_pending:
        return "nothing_to_do"
    run.snap = LisskinsSnapshot(
        order_id=order.id,
        number=order.number,
        skin_item_id=order.skin_item_id,
        custom_id=purchase.custom_id,
        skin_id=purchase.skin_id,
        paid_units=purchase.paid_units,
        cost_units=order.cost_units,
        repeat=purchase.buy_unconfirmed_at is not None,
    )
    try:
        link = parse_tradelink(order.trade_link)
    except ValidationError:
        return await refund(db, run.snap, "invalid_trade_link")
    settled = await _buy_once(db, client, run.snap, link, run)
    if settled is not None:
        return settled
    log.info("orders.lisskins_buy.refused", number=run.snap.number, code=run.refusal)
    # Never another lot (ADR-0013); «sold out» only when the lot is gone or dearer.
    reason = "sold_out" if run.refusal in BUY_SOLD_ERRORS else "source_refused"
    return await refund(db, run.snap, reason, error=run.refusal)


async def _buy_once(  # noqa: PLR0911 -- one return per row of the spec's table
    db: AsyncSession,
    client: LisskinsBuyClient,
    snap: LisskinsSnapshot,
    link: TradeLink,
    run: _Run,
) -> str | None:
    """One buy request: the attempt's outcome, or ``None`` for a lot that cannot be had."""
    try:
        run.sent = True  # from here on an unrecorded exit must not free the order
        report = await client.buy(
            skin_id=snap.skin_id,
            partner=link.partner,
            token=link.token,
            max_price_usd=Decimal(snap.paid_units) / _UNITS_PER_USD,
            custom_id=snap.custom_id,
        )
    except LisskinsForbiddenError:
        return await attention(db, snap, "source_forbidden", outcome="forbidden")
    except LisskinsRateLimitedError as exc:
        run.retry_after = exc.retry_after
        return "rate_limited"
    except LisskinsUnavailableError:
        return await unconfirmed(db, snap)  # it may have gone through: market/info settles it
    except LisskinsError as err:
        if err.code == "custom_id_already_exists" or (snap.repeat and err.code not in _MOVED_ON):
            return await _adopt(db, client, snap)  # a repeat's refusal may be our own first buy
        if err.code in BUY_LINK_ERRORS:
            await remember_rejection(get_redis(), link.url)  # the partner API hears it next
            return await refund(db, snap, "invalid_trade_link", error=err.code)
        if err.code == "insufficient_funds":
            return await refund(db, snap, "source_low_balance", error=err.code)
        run.refusal = err.code
        return None  # sold, dearer than our cap, or another refusal of this lot
    return await record_purchase(db, snap, report)


async def _adopt(db: AsyncSession, client: LisskinsBuyClient, snap: LisskinsSnapshot) -> str:
    """LIS-SKINS knows our ``custom_id``: take its stored purchase, or leave it to the
    reconcile when ``market/info`` cannot show it now."""
    try:
        found = await client.info(custom_ids=[snap.custom_id])
    except (LisskinsError, LisskinsUnavailableError):
        found = []
    report = next((p for p in found if p.custom_id == snap.custom_id), None)
    if report is None:
        return await (held(db, snap) if snap.repeat else unconfirmed(db, snap))
    return await record_purchase(db, snap, report, outcome="adopted")


__all__ = ["ATTEMPT_BUDGET", "MAX_RETRY_AFTER", "RELEASE_BACKOFF", "attempt_lisskins_buy"]
