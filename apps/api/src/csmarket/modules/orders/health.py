"""What is stuck: the numbers behind the order alerts (``infra/prometheus/alerts/orders.yml``).

:func:`measure` is read-only and cheap (three counts over small in-flight sets, one Waxpeer
balance call when asked). The scheduler's ``orders.health`` job turns the result into gauges.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.clock import now
from csmarket.core.config import Settings
from csmarket.core.logging import get_logger
from csmarket.modules.orders.models import Order, SkinTrade
from csmarket.modules.skins.api import TradeClient

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


async def _count(db: AsyncSession, *conditions: object) -> int:
    """Orders (left-joined to their trade) matching ``conditions``."""
    stmt = (
        select(func.count())
        .select_from(Order)
        .outerjoin(SkinTrade, SkinTrade.order_id == Order.id)
        .where(*conditions)  # type: ignore[arg-type]  # SQL expressions
    )
    return int(await db.scalar(stmt) or 0)


async def _waxpeer_balance(client: TradeClient | None) -> Decimal | None:
    """Our balance in USD, or ``None`` on no client or any error."""
    if client is None:
        return None
    try:
        return Decimal(await client.balance_units()) / UNITS_PER_USD
    except Exception as exc:  # noqa: BLE001 -- a gauge keeps its last value; the call is metered
        log.warning("orders.health.balance_failed", error=type(exc).__name__)
        return None


async def measure(db: AsyncSession, client: TradeClient | None, *, settings: Settings) -> Health:
    """Count what is stuck and, with a ``client``, read the Waxpeer balance.

    Args:
        db: A session; nothing is written.
        client: The Waxpeer purchase client, or ``None`` to skip the balance call.
        settings: Reserved for thresholds that become settings.

    Returns:
        The counts, and the balance in USD (``None`` when skipped or unreadable).
    """
    del settings  # the windows are fixed (spec §12); kept so a threshold can become a setting
    at = now()
    paid = await _count(db, Order.status == "paid", Order.paid_at < at - PAID_STUCK_AFTER)
    buying = await _count(
        db,
        Order.status == "buying",
        Order.claimed_at < at - BUYING_STUCK_AFTER,
        # An open attention is already on an admin's list (and its own alert).
        or_(
            SkinTrade.order_id.is_(None),
            SkinTrade.attention_reason.is_(None),
            SkinTrade.resolved_at.is_not(None),
        ),
    )
    unpolled = await _count(
        db,
        Order.status == "trade_sent",
        or_(SkinTrade.last_polled_at.is_(None), SkinTrade.last_polled_at < at - UNPOLLED_AFTER),
    )
    attention = int(
        await db.scalar(
            select(func.count())
            .select_from(SkinTrade)
            .where(SkinTrade.attention_reason.is_not(None), SkinTrade.resolved_at.is_(None))
        )
        or 0
    )
    return Health(
        paid_stuck=paid,
        buying_stuck=buying,
        trade_sent_unpolled=unpolled,
        attention=attention,
        waxpeer_balance_usd=await _waxpeer_balance(client),
    )


__all__ = ["Health", "measure"]
