"""What is stuck: the numbers behind the order alerts (``infra/prometheus/alerts/orders.yml``).

:func:`measure` is read-only and cheap (a few counts over small in-flight sets, the oldest
API order in ``buying``, one Waxpeer balance call when asked). The scheduler's ``orders.health`` job turns the result into gauges.
"""

from __future__ import annotations

import contextlib
import json
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation

from pydantic import BaseModel, ConfigDict
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.clock import now
from csmarket.core.config import Settings
from csmarket.core.logging import get_logger
from csmarket.modules.lisskins.api import LisskinsPurchase
from csmarket.modules.orders.models import Order, SkinTrade
from csmarket.modules.skins.api import TradeClient
from csmarket.modules.skinslink.api import SkinslinkPurchase

log = get_logger("csmarket.orders.health")

#: A ``paid`` order the worker has not picked up after this is a worker problem.
PAID_STUCK_AFTER = timedelta(minutes=5)
#: A ``buying`` order claimed this long ago without an open attention is stuck.
BUYING_STUCK_AFTER = timedelta(minutes=30)
#: A ``trade_sent`` order whose trade was last looked up this long ago (or never).
UNPOLLED_AFTER = timedelta(minutes=30)
#: Waxpeer's integer balance: 1000 units = $1.
UNITS_PER_USD = Decimal(1000)


class Health(BaseModel):
    """One reading of the order pipeline's health."""

    model_config = ConfigDict(frozen=True)

    paid_stuck: int
    buying_stuck: int
    trade_sent_unpolled: int
    #: Trades waiting for an admin (attention set, not resolved).
    attention: int
    #: ``None`` when it was not asked for or Waxpeer did not answer.
    waxpeer_balance_usd: Decimal | None
    #: Age, from ``created_at``, of the oldest API order its partner reads as ``buying``
    #: (open attentions included: the partner waits on them too); 0 when there is none.
    api_buying_oldest_seconds: float = 0.0


#: An order's trade fields, whichever market it is bought at (an order has one of the two).
_ATTENTION = func.coalesce(
    SkinTrade.attention_reason,
    SkinslinkPurchase.attention_reason,
    LisskinsPurchase.attention_reason,
)
_RESOLVED_AT = func.coalesce(
    SkinTrade.resolved_at, SkinslinkPurchase.resolved_at, LisskinsPurchase.resolved_at
)
_POLLED_AT = func.coalesce(
    SkinTrade.last_polled_at, SkinslinkPurchase.last_polled_at, LisskinsPurchase.last_polled_at
)


async def _count(db: AsyncSession, *conditions: object) -> int:
    """Orders (left-joined to their Waxpeer trade or Skinslink purchase) matching
    ``conditions``."""
    stmt = (
        select(func.count())
        .select_from(Order)
        .outerjoin(SkinTrade, SkinTrade.order_id == Order.id)
        .outerjoin(SkinslinkPurchase, SkinslinkPurchase.order_id == Order.id)
        .outerjoin(LisskinsPurchase, LisskinsPurchase.order_id == Order.id)
        .where(*conditions)  # type: ignore[arg-type]  # SQL expressions
    )
    return int(await db.scalar(stmt) or 0)


async def open_attentions(db: AsyncSession) -> int:
    """Trades and purchases of every source waiting for an admin."""
    total = 0
    for table in (SkinTrade, SkinslinkPurchase, LisskinsPurchase):
        total += int(
            await db.scalar(
                select(func.count())
                .select_from(table)
                .where(table.attention_reason.is_not(None), table.resolved_at.is_(None))
            )
            or 0
        )
    return total


async def _waxpeer_balance(client: TradeClient | None) -> Decimal | None:
    """Our balance in USD, or ``None`` on no client or any error."""
    if client is None:
        return None
    try:
        return Decimal(await client.balance_units()) / UNITS_PER_USD
    except Exception as exc:  # noqa: BLE001 -- a gauge keeps its last value; the call is metered
        log.warning("orders.health.balance_failed", error=type(exc).__name__)
        return None


async def _api_buying_oldest(db: AsyncSession, at: datetime) -> float:
    """Seconds since the oldest API order that reads ``buying`` to its partner was created.

    Mirrors ``public_view.public_status``'s ``buying``: ``paid`` / ``buying``, and ``failed`` /
    ``returned`` held for support (no refund yet). 0 when there is none.
    """
    oldest = await db.scalar(
        select(func.min(Order.created_at)).where(
            Order.channel == "api",
            Order.refunded_at.is_(None),
            or_(
                Order.status.in_(("paid", "buying")),
                Order.status.in_(("failed", "returned")),
            ),
        )
    )
    return 0.0 if oldest is None else max(0.0, (at - oldest).total_seconds())


async def measure(db: AsyncSession, client: TradeClient | None, *, settings: Settings) -> Health:
    """Count what is stuck and, with a ``client``, read the Waxpeer balance.

    Args:
        db: A session; nothing is written.
        client: The Waxpeer purchase client, or ``None`` to skip the balance call.
        settings: Reserved for thresholds that become settings.

    Returns:
        The counts, the oldest API order in ``buying``, and the balance in USD (``None``
        when skipped or unreadable).
    """
    del settings  # the windows are fixed (spec §12); kept so a threshold can become a setting
    at = now()
    paid = await _count(db, Order.status == "paid", Order.paid_at < at - PAID_STUCK_AFTER)
    buying = await _count(
        db,
        Order.status == "buying",
        Order.claimed_at < at - BUYING_STUCK_AFTER,
        # An open attention is already on an admin's list (and its own alert).
        or_(_ATTENTION.is_(None), _RESOLVED_AT.is_not(None)),
    )
    unpolled = await _count(
        db,
        Order.status == "trade_sent",
        or_(_POLLED_AT.is_(None), at - UNPOLLED_AFTER > _POLLED_AT),
    )
    attention = await open_attentions(db)
    return Health(
        paid_stuck=paid,
        buying_stuck=buying,
        trade_sent_unpolled=unpolled,
        attention=attention,
        waxpeer_balance_usd=await _waxpeer_balance(client),
        api_buying_oldest_seconds=await _api_buying_oldest(db, at),
    )


#: The last good Waxpeer balance read, for the admin dashboard (ruling R10).
BALANCE_KEY = "orders:waxpeer:balance"
_BALANCE_TTL_SECONDS = 3600


async def cache_balance(redis: Redis, usd: Decimal, *, at: datetime) -> None:
    """Keep a good balance read for the dashboard (the ``orders.health`` job only).

    A Redis failure is logged and swallowed: the gauges matter more than the copy.
    """
    try:
        value = json.dumps({"usd": str(usd), "read_at": at.isoformat()})
        await redis.set(BALANCE_KEY, value, ex=_BALANCE_TTL_SECONDS)
    except RedisError as exc:
        log.warning("orders.health.balance_cache_failed", error=type(exc).__name__)


async def cached_balance(redis: Redis) -> tuple[Decimal | None, datetime | None]:
    """The last cached balance and when it was read; ``(None, None)`` when unknown."""
    with contextlib.suppress(RedisError, ValueError, KeyError, TypeError, InvalidOperation):
        raw = await redis.get(BALANCE_KEY)
        if raw is not None:
            data = json.loads(raw)
            return Decimal(data["usd"]), datetime.fromisoformat(data["read_at"])
    return None, None


__all__ = [
    "BALANCE_KEY",
    "Health",
    "cache_balance",
    "cached_balance",
    "measure",
    "open_attentions",
]
