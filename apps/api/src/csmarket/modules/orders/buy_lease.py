"""An order's buy lease and the attempt's exits (``orders.buying``).

One attempt at a time per order: :func:`take_lease` is one atomic UPDATE that holds a
``buying`` order whose trade is ``buy_pending`` for :data:`BUY_LEASE` (``next_check_at``);
:func:`release` gives it back only while it is still this attempt's. When an attempt dies
after its buy request went out (a timeout, a shutdown, an unexpected error) the caller's
session may be mid-statement: :func:`secure` records the buy as unconfirmed in a fresh
session, and when even that fails the lease is kept, so it lapses as a dead attempt and
no one buys again within it.
"""

from __future__ import annotations

import asyncio
import contextlib
from datetime import datetime, timedelta

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.clock import now
from csmarket.core.logging import get_logger
from csmarket.modules.orders import buy_writes
from csmarket.modules.orders.buy_writes import BuySnapshot
from csmarket.modules.orders.models import Order, SkinTrade

log = get_logger("csmarket.orders.buying")

#: How long one attempt holds its order against a second one. Longer than the slowest
#: attempt (six Waxpeer calls at ``waxpeer_buy_timeout_seconds``); an attempt that dies
#: mid-way leaves the order to the reconcile sweep once it lapses.
BUY_LEASE = timedelta(minutes=5)
#: How long :func:`secure` may wait for the rows (a lock the dead attempt still holds).
_SECURE_SECONDS = 10.0


async def take_lease(db: AsyncSession, order_id: str) -> datetime | None:
    """Hold a ``buying`` order whose buy is pending for :data:`BUY_LEASE`.

    Returns:
        The lease (the ``next_check_at`` written), or ``None`` when the order is not
        buying, its buy is no longer pending, or another attempt holds it.
    """
    at = now()
    pending = (
        select(SkinTrade.order_id)
        .where(SkinTrade.order_id == Order.id, SkinTrade.buy_pending.is_(True))
        .exists()
    )
    lease = await db.scalar(
        update(Order)
        .where(
            Order.id == order_id,
            Order.status == "buying",
            pending,
            or_(Order.next_check_at.is_(None), Order.next_check_at <= at),
        )
        .values(next_check_at=at + BUY_LEASE)
        .returning(Order.next_check_at)
    )
    await db.commit()
    return lease


async def release(
    db: AsyncSession, order_id: str, lease: datetime, *, after: timedelta = timedelta(0)
) -> None:
    """Make the order due again ``after`` from now — only if the lease is still this
    attempt's."""
    await db.execute(
        update(Order)
        .where(Order.id == order_id, Order.status == "buying", Order.next_check_at == lease)
        .values(next_check_at=now() + after)
    )
    await db.commit()


def _fresh(db: AsyncSession) -> AsyncSession:
    """A new session on ``db``'s engine (``db`` may be broken mid-statement)."""
    return AsyncSession(bind=db.bind, expire_on_commit=False)


async def discard(db: AsyncSession) -> None:
    """Roll ``db`` back (or close it) so the rows it may still lock are free."""
    try:
        await db.rollback()
    except Exception:  # noqa: BLE001 -- a broken connection: give it back instead
        with contextlib.suppress(Exception):
            await db.close()


async def release_fresh(db: AsyncSession, order_id: str, lease: datetime) -> None:
    """:func:`release` through a fresh session; a failure keeps the lease (it lapses)."""
    try:
        async with _fresh(db) as fresh:
            await release(fresh, order_id, lease)
    except Exception as exc:  # noqa: BLE001 -- the lease then lapses by itself
        log.warning("orders.buy.release_failed", order_id=order_id, error=type(exc).__name__)


async def secure(db: AsyncSession, snap: BuySnapshot) -> bool | None:
    """Record a sent buy as unconfirmed through a fresh session.

    Returns:
        ``True`` when it marked the trade, ``False`` when the outcome was already on
        record, ``None`` when it could not write (the caller then keeps the lease).
    """
    try:
        async with asyncio.timeout(_SECURE_SECONDS), _fresh(db) as fresh:
            return await buy_writes.secure_sent(fresh, snap)
    except Exception as exc:  # noqa: BLE001 -- keep the lease; the error is logged
        log.error("orders.buy.unrecorded", number=snap.number, error=type(exc).__name__)  # noqa: TRY400
        return None


__all__ = ["BUY_LEASE", "discard", "release", "release_fresh", "secure", "take_lease"]
