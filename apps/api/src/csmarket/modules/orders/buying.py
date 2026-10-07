"""The worker buys paid orders at Waxpeer — each order at most once (rulings R3, R4, R6).

- :func:`drain_paid` — the ``orders`` queue's drain: claims ``paid`` orders oldest first
  (``FOR UPDATE SKIP LOCKED``), moves them to ``buying``, opens their ``skin_trades`` row
  (``project_id`` = the order id, ``buy_pending``), commits, then runs :func:`attempt_buy`
  for each in its own transactions.
- :func:`attempt_buy` — the one buy path, also run by the reconcile sweep for a trade still
  ``buy_pending``:

  1. take the order's lease first (``orders.buy_lease``: one UPDATE that requires
     ``buying`` and ``buy_pending``), then read the snapshot — a second attempt (the sweep
     racing the worker) finds the lease held or the buy settled and does nothing; the
     attempt's time budget starts before the lease, so it ends before the lease does;
  2. a trade link that does not parse → refund ``invalid_trade_link``;
  3. **lookup first** (``check_project_ids``): a failure buys nothing and retries later; a
     403 sets the attention ``source_forbidden``; a found trade is adopted — never rebought;
     several live ones set ``ambiguous_trade``;
  4. buy the chosen listing at the units agreed at checkout; a refusal (sold, price moved,
     a 4xx) → the cheapest other ``auto`` listing within ``paid_units × (1 + ceiling)``,
     once; a refusal that names the trade link → refund ``invalid_trade_link``; low balance (by Waxpeer's words or ``GET /v1/user``) → refund at once; 403 →
     attention, ``buy_pending`` kept; 429 → retried next tick; a lost answer or a 5xx →
     ``buy_unconfirmed_at``, resolved by lookup (R3), never by buying again.

No lock is held across a Waxpeer call: every write (``orders.buy_writes``) locks the order,
then the trade (ruling K), re-checks ``status == "buying"`` and ``buy_pending``, writes and
commits — a sweep may have moved the rows meanwhile, and then nothing is written. Once a
buy request went out, an exit that could not record its outcome marks it unconfirmed in a
fresh session, or keeps the lease. Log lines carry the order number and the outcome, never
the trade link, its partner or token, or a Waxpeer URL.
"""

from __future__ import annotations

import asyncio
import os
import socket
from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.clock import now
from csmarket.core.config import Settings, get_settings
from csmarket.core.errors import ValidationError
from csmarket.core.logging import get_logger
from csmarket.core.metrics import OrderBuyOutcome, record_order_buy
from csmarket.modules.orders.buy_lease import (
    BUY_LEASE,
    discard,
    release,
    release_fresh,
    secure,
    take_lease,
)
from csmarket.modules.orders.buy_rules import link_refused, low_balance, substitute
from csmarket.modules.orders.buy_writes import (
    BuySnapshot,
    adopt,
    attention,
    park,
    record_bought,
    refund,
    unconfirmed,
)
from csmarket.modules.orders.fsm import move
from csmarket.modules.orders.models import Order, SkinTrade
from csmarket.modules.orders.skinslink_buying import attempt_skinslink_buy
from csmarket.modules.orders.substitutes import pending_buy
from csmarket.modules.orders.trades import FAILED_STATUS, AmbiguousTradeError, pick_trade
from csmarket.modules.realtime.api import nudge
from csmarket.modules.skins.api import (
    TradeClient,
    WaxpeerError,
    WaxpeerForbiddenError,
    WaxpeerRateLimitedError,
    WaxpeerTrade,
    WaxpeerUnavailableError,
    trade_client,
)
from csmarket.modules.skinslink.api import SkinslinkPurchaseClient, client_for
from csmarket.modules.users.api import TradeLink, parse_tradelink

log = get_logger("csmarket.orders.buying")

#: An attempt's time budget, counted from before its lease is taken: it ends at least
#: 30 s before the lease does.
ATTEMPT_BUDGET = BUY_LEASE - timedelta(seconds=30)
#: How long an attempt that hit Waxpeer's 403, its 429, or a failed lookup leaves the order
#: before the next one (bounds the lookups a misconfigured key, a rate limit or an outage
#: causes: without it every reconcile tick would ask again for every pending buy).
RELEASE_BACKOFF: dict[str, timedelta] = {
    "forbidden": timedelta(seconds=60),
    "rate_limited": timedelta(seconds=20),
    "lookup_later": timedelta(seconds=20),
}
#: The longest a 429's own ``retry_after`` may hold an order (a longer hint is capped).
MAX_RETRY_AFTER = BUY_LEASE
#: Outcomes that are not a buy attempt's result (nothing was tried, or nothing written).
_UNCOUNTED = frozenset({"nothing_to_do", "lookup_later"})


def worker_id() -> str:
    """``hostname:pid`` — who claimed an order (``orders.claimed_by``)."""
    return f"{socket.gethostname()}:{os.getpid()}"[:64]


async def _claim(db: AsyncSession, *, limit: int) -> list[tuple[str, str]]:
    """Move up to ``limit`` ``paid`` orders, oldest first, to ``buying``; commit.

    Returns:
        ``(order id, source)`` of each claimed order.
    """
    orders = (
        await db.scalars(
            select(Order)
            .where(Order.status == "paid")
            .order_by(Order.paid_at, Order.created_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
            .execution_options(populate_existing=True)
        )
    ).all()
    at, me = now(), worker_id()
    for order in orders:
        move(order, "buying")
        order.claimed_at, order.claimed_by, order.next_check_at = at, me, at
        db.add(pending_buy(order, units=order.cost_units, key=order.id))
    for order in orders:
        await nudge(db, user_id=order.user_id, number=order.number)
    claimed = [(order.id, order.source) for order in orders]
    await db.commit()
    return claimed


async def drain_paid(
    db: AsyncSession,
    *,
    client: TradeClient | None = None,
    skinslink_client: SkinslinkPurchaseClient | None = None,
    settings: Settings | None = None,
    limit: int = 10,
) -> int:
    """Claim up to ``limit`` paid orders and buy each — the worker's ``orders`` drain.

    One order's failure never stops the batch: it is rolled back and logged, and the order
    stays ``buying`` with ``buy_pending`` for the reconcile sweep once its lease lapses.

    Args:
        db: The drainer's own session; committed here.
        client: Waxpeer; the process's :func:`trade_client` when omitted.
        skinslink_client: Skinslink; built (buy timeout) when a Skinslink order is claimed.
        settings: The process settings when omitted.
        limit: Orders claimed per call.

    Returns:
        How many orders were claimed (0 = the queue is dry).
    """
    settings = settings or get_settings()
    claimed = await _claim(db, limit=limit)
    if not claimed:
        return 0
    client = client or trade_client(settings)
    for order_id, source in claimed:
        try:
            if source == "skinslink":
                skinslink_client = skinslink_client or client_for(
                    settings, timeout_seconds=settings.skinslink_buy_timeout_seconds
                )
                await attempt_skinslink_buy(
                    db, skinslink_client, order_id=order_id, settings=settings, waxpeer=client
                )
            else:
                await attempt_buy(db, client, order_id=order_id, settings=settings)
        except Exception as exc:  # noqa: BLE001 -- one poisoned order must not stop the batch
            await db.rollback()
            # The type only, no traceback: an error's text can carry bound SQL parameters.
            log.error("orders.buy.crashed", order_id=order_id, error=type(exc).__name__)  # noqa: TRY400
    return len(claimed)


class _Run:
    """One attempt's progress: its snapshot once read, whether a buy request went out, and
    the wait a 429 asked for."""

    __slots__ = ("retry_after", "sent", "snap")

    def __init__(self) -> None:
        self.snap: BuySnapshot | None = None
        self.sent = False
        self.retry_after: float | None = None

    def backoff(self, outcome: str) -> timedelta:
        """How long the order waits after ``outcome``: :data:`RELEASE_BACKOFF`, or Waxpeer's
        own ``retry_after`` when it asked for longer (capped at :data:`MAX_RETRY_AFTER`)."""
        wait = RELEASE_BACKOFF.get(outcome, timedelta(0))
        if self.retry_after is not None and wait > timedelta(0):
            wait = max(wait, min(timedelta(seconds=self.retry_after), MAX_RETRY_AFTER))
        return wait


async def attempt_buy(
    db: AsyncSession, client: TradeClient, *, order_id: str, settings: Settings
) -> str:
    """Buy order ``order_id`` at Waxpeer, unless it was bought or is being bought.

    The lease comes first (one atomic UPDATE that also requires ``buy_pending``), the
    snapshot is read after it: a second attempt can never act on a ``buy_pending`` it read
    before the first one settled the buy. The attempt is bounded by :data:`ATTEMPT_BUDGET`
    counted from before the lease, so it never outlives its lease. Once a buy request went
    out, every exit that did not record the outcome marks it unconfirmed (fresh session)
    or keeps the lease.

    Args:
        db: Session; each step commits its own short transaction.
        client: Waxpeer.
        order_id: The order.
        settings: For the substitute ceiling and the listings budget.

    Returns:
        The outcome: ``bought``, ``adopted``, ``sold_out``, ``low_balance``,
        ``invalid_link``, ``forbidden``, ``rate_limited``, ``unconfirmed``, ``unrecorded``
        (a sent buy timed out and even the unconfirmed mark could not be written: the lease
        lapses as a dead attempt's), ``ambiguous``, ``stale_bought``, ``lookup_later`` or
        ``nothing_to_do``.
    """
    deadline = asyncio.get_running_loop().time() + ATTEMPT_BUDGET.total_seconds()
    lease = await take_lease(db, order_id)
    if lease is None:
        return "nothing_to_do"
    run = _Run()
    try:
        async with asyncio.timeout_at(deadline):
            outcome = await _leased(db, client, order_id=order_id, settings=settings, run=run)
    except TimeoutError:
        outcome = await _after_timeout(db, order_id=order_id, lease=lease, run=run)
    except BaseException:
        if run.sent and run.snap is not None:
            await discard(db)
            await secure(db, run.snap)  # the lease is kept either way: it lapses
        raise
    else:
        await release(db, order_id, lease, after=run.backoff(outcome))
    if run.snap is None:
        return outcome
    if outcome not in _UNCOUNTED:
        record_order_buy(cast(OrderBuyOutcome, outcome))  # every other outcome is in the set
    log.info("orders.buy", number=run.snap.number, outcome=outcome)
    return outcome


async def _leased(
    db: AsyncSession, client: TradeClient, *, order_id: str, settings: Settings, run: _Run
) -> str:
    """Read the snapshot under the lease, then run the attempt."""
    read = await _read(db, order_id)
    if read is None:
        return "nothing_to_do"
    run.snap, raw_link = read
    return await _attempt(db, client, snap=run.snap, raw_link=raw_link, settings=settings, run=run)


async def _after_timeout(db: AsyncSession, *, order_id: str, lease: datetime, run: _Run) -> str:
    """The budget ran out: nothing sent → due again; a sent buy → recorded as unconfirmed
    (fresh session), or the lease is kept when even that cannot be written."""
    await discard(db)
    if not run.sent or run.snap is None:
        await release_fresh(db, order_id, lease)
        return "lookup_later"
    marked = await secure(db, run.snap)
    if marked is None:
        return "unrecorded"  # nothing written: the lease lapses as a dead attempt's
    await release_fresh(db, order_id, lease)
    return "unconfirmed" if marked else "nothing_to_do"


async def _read(db: AsyncSession, order_id: str) -> tuple[BuySnapshot, str] | None:
    """The order to buy and its stored trade link, or ``None``; ends the read transaction."""
    order = await db.scalar(
        select(Order).where(Order.id == order_id).execution_options(populate_existing=True)
    )
    trade = await db.scalar(
        select(SkinTrade)
        .where(SkinTrade.order_id == order_id)
        .execution_options(populate_existing=True)
    )
    result = None
    if order is not None and trade is not None and order.status == "buying" and trade.buy_pending:
        snap = BuySnapshot(
            order_id=order.id,
            number=order.number,
            skin_item_id=order.skin_item_id,
            listing_id=trade.listing_id,
            paid_units=trade.paid_units,
            cost_units=order.cost_units,
            unconfirmed=trade.buy_unconfirmed_at is not None,
        )
        result = (snap, order.trade_link)
    await db.commit()
    return result


async def _attempt(
    db: AsyncSession,
    client: TradeClient,
    *,
    snap: BuySnapshot,
    raw_link: str,
    settings: Settings,
    run: _Run,
) -> str:
    """Steps 2–4 of :func:`attempt_buy` (the order is leased)."""
    try:
        link = parse_tradelink(raw_link)
    except ValidationError:
        return await refund(db, snap, "invalid_trade_link")
    try:
        trades = await client.check_project_ids([snap.order_id])
        found = pick_trade(trades, None)
    except WaxpeerForbiddenError:
        return await attention(db, snap, "source_forbidden", outcome="forbidden")
    except WaxpeerRateLimitedError as exc:
        run.retry_after = exc.retry_after_seconds
        return "lookup_later"  # nothing was sent: look again after the backoff, then buy
    except (WaxpeerUnavailableError, WaxpeerError):
        return "lookup_later"  # nothing was sent: look again after the backoff, then buy
    except AmbiguousTradeError:
        return await attention(db, snap, "ambiguous_trade", outcome="ambiguous", settle=True)
    return await _after_lookup(
        db, client, snap=snap, trades=trades, found=found, link=link, settings=settings, run=run
    )


async def _after_lookup(
    db: AsyncSession,
    client: TradeClient,
    *,
    snap: BuySnapshot,
    trades: Sequence[WaxpeerTrade],
    found: WaxpeerTrade | None,
    link: TradeLink,
    settings: Settings,
    run: _Run,
) -> str:
    """Adopt a live trade; never a failed (6) one — refused attempts only → buy as usual.

    A trade that still carries a lost answer (``snap.unconfirmed``) is parked whatever the
    lookup shows, an empty one included. That is a belt: ``unconfirmed``/``secure_sent``
    end ``buy_pending`` and ``retry_buy`` clears ``buy_unconfirmed_at``, so today no
    attempt reads both; if a future writer ever leaves them together, a lost answer is
    still resolved by the reconcile rule (R3), never by buying again.
    """
    if found is not None and found.status != FAILED_STATUS:
        return await adopt(db, snap, found)
    # None found, or only failed (6) ones — never adopted as the order's trade.
    if any(t.release_date or t.penalties or t.is_released for t in trades):
        # One was accepted: the skin may have reached the buyer. Nothing is bought.
        return await attention(db, snap, "ambiguous_trade", outcome="ambiguous", settle=True)
    if snap.unconfirmed:
        return await park(db, snap)  # a lost answer: the reconcile rule decides (R3)
    return await _buy(db, client, snap=snap, link=link, settings=settings, run=run)


async def _buy(  # noqa: PLR0911 -- one return per R6 outcome reads as the ruling
    db: AsyncSession,
    client: TradeClient,
    *,
    snap: BuySnapshot,
    link: TradeLink,
    settings: Settings,
    run: _Run,
) -> str:
    """The chosen listing at the agreed units, then at most one substitute (R4, R6)."""
    base = snap.cost_units if snap.cost_units is not None else snap.paid_units
    ceiling = int(base * (1 + settings.order_substitute_ceiling))
    queue: list[tuple[int, int]] = [(snap.listing_id, snap.paid_units)]
    tried: set[int] = set()
    while queue:
        listing_id, units = queue.pop(0)
        tried.add(listing_id)
        try:
            run.sent = True  # from here on an unrecorded exit must not free the order
            bought = await client.buy_one_p2p(
                item_id=listing_id,
                price_units=units,
                partner=link.partner,
                token=link.token,
                project_id=snap.order_id,
            )
        except WaxpeerForbiddenError:
            return await attention(db, snap, "source_forbidden", outcome="forbidden")
        except WaxpeerRateLimitedError as exc:
            run.retry_after = exc.retry_after_seconds
            return "rate_limited"  # nothing bought; retried after the backoff
        except WaxpeerUnavailableError:
            return await unconfirmed(db, snap)  # the buy may have happened: resolve by lookup
        except WaxpeerError as err:  # a refusal (incl. WaxpeerBuyRefusedError) or HTTP error
            if err.status >= 500:
                return await unconfirmed(db, snap)  # a 5xx may have bought it
            if link_refused(err):  # the buyer's link: every listing would refuse it
                return await refund(db, snap, "invalid_trade_link")
            if await low_balance(client, err, units):
                return await refund(db, snap, "source_low_balance")
            log.info("orders.buy.refused", number=snap.number, status=err.status)
            if len(tried) == 1:
                nxt = await substitute(
                    db, client, snap=snap, ceiling=ceiling, tried=tried, settings=settings
                )
                if nxt is not None:
                    queue.append(nxt)
            continue
        return await record_bought(db, snap, bought, listing_id=listing_id, units=units)
    return await refund(db, snap, "sold_out")


__all__ = [
    "ATTEMPT_BUDGET",
    "BUY_LEASE",
    "MAX_RETRY_AFTER",
    "RELEASE_BACKOFF",
    "attempt_buy",
    "drain_paid",
    "worker_id",
]
