"""The worker buys paid orders at Waxpeer — each order at most once (rulings R3, R4, R6).

- :func:`drain_paid` — the ``orders`` queue's drain: claims ``paid`` orders oldest first
  (``FOR UPDATE SKIP LOCKED``), moves them to ``buying``, opens their ``skin_trades`` row
  (``project_id`` = the order id, ``buy_pending``), commits, then runs :func:`attempt_buy`
  for each in its own transactions.
- :func:`attempt_buy` — the one buy path, also run by the reconcile sweep for a trade still
  ``buy_pending``:

  1. read unlocked; nothing to do unless the order is ``buying`` and the trade
     ``buy_pending``; take the order's lease (``next_check_at``), so a second attempt —
     the sweep racing the worker — finds it held and does nothing;
  2. a trade link that does not parse → refund ``invalid_trade_link``;
  3. **lookup first** (``check_project_ids``): a failure buys nothing and retries later; a
     403 sets the attention ``waxpeer_forbidden``; a found trade is adopted — never rebought;
     several live ones set ``ambiguous_trade``;
  4. buy the chosen listing at the units agreed at checkout; a refusal (sold, price moved,
     a 4xx) → the cheapest other ``auto`` listing within ``paid_units × (1 + ceiling)``,
     once; low balance (by Waxpeer's words or ``GET /v1/user``) → refund at once; 403 →
     attention, ``buy_pending`` kept; 429 → retried next tick; a lost answer or a 5xx →
     ``buy_unconfirmed_at``, resolved by lookup (R3), never by buying again.

No lock is held across a Waxpeer call: every write (``orders.buy_writes``) locks the order,
then the trade (ruling K), re-checks ``status == "buying"`` and ``buy_pending``, writes and
commits — a sweep may have moved the rows meanwhile, and then nothing is written. Log lines carry the order
number and the outcome, never the trade link, its partner or token, or a Waxpeer URL.
"""

from __future__ import annotations

import os
import socket
from datetime import timedelta
from typing import Any, cast

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.clock import now
from csmarket.core.config import Settings, get_settings
from csmarket.core.errors import ValidationError
from csmarket.core.logging import get_logger
from csmarket.core.metrics import OrderBuyOutcome, record_order_buy
from csmarket.core.redis import get_redis
from csmarket.modules.orders.buy_writes import (
    BuySnapshot,
    adopt,
    attention,
    record_bought,
    refund,
    unconfirmed,
)
from csmarket.modules.orders.fsm import move
from csmarket.modules.orders.models import Order, SkinTrade
from csmarket.modules.orders.trades import AmbiguousTradeError, pick_trade
from csmarket.modules.skins.api import (
    SkinItem,
    TradeClient,
    WaxpeerError,
    WaxpeerForbiddenError,
    WaxpeerRateLimitedError,
    WaxpeerUnavailableError,
    listings_budget,
    listings_for,
    trade_client,
)
from csmarket.modules.users.api import TradeLink, parse_tradelink

log = get_logger("csmarket.orders.buying")

#: How long one attempt holds its order against a second one. Longer than the slowest
#: attempt (six Waxpeer calls at ``waxpeer_buy_timeout_seconds``); an attempt that dies
#: mid-way leaves the order to the reconcile sweep once it lapses.
BUY_LEASE = timedelta(minutes=5)
_LOW_BALANCE_HINTS = ("not enough balance", "insufficient balance", "insufficient funds")
#: Outcomes that are not a buy attempt's result (nothing was tried, or nothing written).
_UNCOUNTED = frozenset({"nothing_to_do", "lookup_later"})


def worker_id() -> str:
    """``hostname:pid`` — who claimed an order (``orders.claimed_by``)."""
    return f"{socket.gethostname()}:{os.getpid()}"[:64]


async def _claim(db: AsyncSession, *, limit: int) -> list[str]:
    """Move up to ``limit`` ``paid`` orders, oldest first, to ``buying``; commit."""
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
        db.add(
            SkinTrade(
                order_id=order.id,
                project_id=order.id,
                listing_id=order.listing_id,
                paid_units=order.cost_units,
                buy_pending=True,
                seller={},
            )
        )
    claimed = [order.id for order in orders]
    await db.commit()
    return claimed


async def drain_paid(
    db: AsyncSession,
    *,
    client: TradeClient | None = None,
    settings: Settings | None = None,
    limit: int = 10,
) -> int:
    """Claim up to ``limit`` paid orders and buy each — the worker's ``orders`` drain.

    One order's failure never stops the batch: it is rolled back and logged, and the order
    stays ``buying`` with ``buy_pending`` for the reconcile sweep once its lease lapses.

    Args:
        db: The drainer's own session; committed here.
        client: Waxpeer; the process's :func:`trade_client` when omitted.
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
    for order_id in claimed:
        try:
            await attempt_buy(db, client, order_id=order_id, settings=settings)
        except Exception as exc:  # noqa: BLE001 -- one poisoned order must not stop the batch
            await db.rollback()
            # The type only, no traceback: an error's text can carry bound SQL parameters.
            log.error("orders.buy.crashed", order_id=order_id, error=type(exc).__name__)  # noqa: TRY400
    return len(claimed)


async def attempt_buy(
    db: AsyncSession, client: TradeClient, *, order_id: str, settings: Settings
) -> str:
    """Buy order ``order_id`` at Waxpeer, unless it was bought or is being bought.

    Args:
        db: Session; each step commits its own short transaction.
        client: Waxpeer.
        order_id: The order.
        settings: For the substitute ceiling and the listings budget.

    Returns:
        The outcome: ``bought``, ``adopted``, ``sold_out``, ``low_balance``,
        ``invalid_link``, ``forbidden``, ``rate_limited``, ``unconfirmed``, ``ambiguous``,
        ``lookup_later`` or ``nothing_to_do``.
    """
    read = await _read(db, order_id)
    if read is None or not await _take_lease(db, order_id):
        return "nothing_to_do"
    snap, raw_link = read
    outcome = await _attempt(db, client, snap=snap, raw_link=raw_link, settings=settings)
    await _release(db, order_id)
    if outcome not in _UNCOUNTED:
        record_order_buy(cast(OrderBuyOutcome, outcome))  # every other outcome is in the set
    log.info("orders.buy", number=snap.number, outcome=outcome)
    return outcome


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
        )
        result = (snap, order.trade_link)
    await db.commit()
    return result


async def _take_lease(db: AsyncSession, order_id: str) -> bool:
    """Hold the order for :data:`BUY_LEASE`; ``False`` when another attempt holds it."""
    at = now()
    held = await db.execute(
        update(Order)
        .where(
            Order.id == order_id,
            Order.status == "buying",
            or_(Order.next_check_at.is_(None), Order.next_check_at <= at),
        )
        .values(next_check_at=at + BUY_LEASE)
    )
    await db.commit()
    return bool(getattr(held, "rowcount", 0) == 1)


async def _release(db: AsyncSession, order_id: str) -> None:
    """Make the order due again: the next sweep tick looks at it."""
    await db.execute(
        update(Order)
        .where(Order.id == order_id, Order.status == "buying")
        .values(next_check_at=now())
    )
    await db.commit()


async def _attempt(
    db: AsyncSession, client: TradeClient, *, snap: BuySnapshot, raw_link: str, settings: Settings
) -> str:
    """Steps 2–4 of :func:`attempt_buy` (the order is leased)."""
    try:
        link = parse_tradelink(raw_link)
    except ValidationError:
        return await refund(db, snap, "invalid_trade_link")
    try:
        found = pick_trade(await client.check_project_ids([snap.order_id]), None)
    except WaxpeerForbiddenError:
        return await attention(db, snap, "waxpeer_forbidden", outcome="forbidden")
    except (WaxpeerUnavailableError, WaxpeerError):
        return "lookup_later"  # nothing was sent: look again next tick, then buy
    except AmbiguousTradeError:
        return await attention(db, snap, "ambiguous_trade", outcome="ambiguous", settle=True)
    if found is not None:
        return await adopt(db, snap, found)
    return await _buy(db, client, snap=snap, link=link, settings=settings)


async def _buy(  # noqa: PLR0911 -- one return per R6 outcome reads as the ruling
    db: AsyncSession, client: TradeClient, *, snap: BuySnapshot, link: TradeLink, settings: Settings
) -> str:
    """The chosen listing at the agreed units, then at most one substitute (R4, R6)."""
    ceiling = int(snap.paid_units * (1 + settings.order_substitute_ceiling))
    queue: list[tuple[int, int]] = [(snap.listing_id, snap.paid_units)]
    tried: set[int] = set()
    while queue:
        listing_id, units = queue.pop(0)
        tried.add(listing_id)
        try:
            bought = await client.buy_one_p2p(
                item_id=listing_id,
                price_units=units,
                partner=link.partner,
                token=link.token,
                project_id=snap.order_id,
            )
        except WaxpeerForbiddenError:
            return await attention(db, snap, "waxpeer_forbidden", outcome="forbidden")
        except WaxpeerRateLimitedError:
            return "rate_limited"  # nothing bought; the next tick retries
        except WaxpeerUnavailableError:
            return await unconfirmed(db, snap)  # the buy may have happened: resolve by lookup
        except WaxpeerError as err:  # a refusal (incl. WaxpeerBuyRefusedError) or HTTP error
            if err.status >= 500:
                return await unconfirmed(db, snap)  # a 5xx may have bought it
            if await _low_balance(client, err, units):
                return await refund(db, snap, "waxpeer_low_balance")
            log.info("orders.buy.refused", number=snap.number, status=err.status)
            if len(tried) == 1:
                nxt = await _substitute(
                    db, client, snap=snap, ceiling=ceiling, tried=tried, settings=settings
                )
                if nxt is not None:
                    queue.append(nxt)
            continue
        return await record_bought(db, snap, bought, listing_id=listing_id, units=units)
    return await refund(db, snap, "sold_out")


async def _low_balance(client: TradeClient, err: WaxpeerError, units: int) -> bool:
    """Waxpeer named low balance, or our Waxpeer wallet holds less than ``units``.

    A balance call that fails counts as "not low": the refusal then reads as sold.
    """
    text = f"{err} {err.body}".lower()
    if any(hint in text for hint in _LOW_BALANCE_HINTS):
        return True
    try:
        return await client.balance_units() < units
    except (WaxpeerError, WaxpeerUnavailableError):
        return False


class _Search:
    """A :class:`TradeClient` as the listings read's ``SearchClient``."""

    def __init__(self, client: TradeClient) -> None:
        self._client = client

    async def search_listings(
        self,
        names: list[str],
        *,
        game: str = "csgo",  # noqa: ARG002 -- SearchClient's signature; we only buy CS2
    ) -> dict[str, list[dict[str, Any]]]:  # Any: raw Waxpeer listing rows
        """Live listings by name (CS2 only, whatever ``game`` says)."""
        return await self._client.search_listings(names)


async def _substitute(
    db: AsyncSession,
    client: TradeClient,
    *,
    snap: BuySnapshot,
    ceiling: int,
    tried: set[int],
    settings: Settings,
) -> tuple[int, int] | None:
    """The cheapest other ``auto`` listing of the item at most ``ceiling`` units, if any.

    Read through the item page's cached, budgeted listings read (Waxpeer's spelling of the
    name, phase included).
    """
    item = await db.get(SkinItem, snap.skin_item_id)
    if item is not None:
        db.expunge(item)  # read below with no transaction open
    await db.commit()
    if item is None:  # pragma: no cover - a foreign key
        return None
    rows, _ = await listings_for(
        item,
        client=_Search(client),
        redis=get_redis(),
        budget_per_minute=listings_budget(settings),
    )
    fits = sorted(
        (row.price_units, row.listing_id)
        for row in rows
        if row.listing_id not in tried and 0 < row.price_units <= ceiling
    )
    return (fits[0][1], fits[0][0]) if fits else None


__all__ = ["BUY_LEASE", "attempt_buy", "drain_paid", "worker_id"]
