"""The Skinslink merchant balance (spec 2026-10-06 §7): read every 5 minutes by the
``skinslink.balance`` job, cached for the admin dashboard and exported as gauges
(``SkinslinkBalanceLow``). A failed read keeps the last good copy and stamp."""

from __future__ import annotations

import contextlib
import json
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Protocol

from redis.asyncio import Redis
from redis.exceptions import RedisError

from csmarket.core.clock import now
from csmarket.core.config import Settings
from csmarket.core.logging import get_logger
from csmarket.core.metrics import set_skinslink_balance
from csmarket.modules.skinslink.client import (
    Balance,
    SkinslinkError,
    SkinslinkUnavailableError,
)

log = get_logger("csmarket.skinslink.balance")

#: The last good balance read (``docs/architecture/cache-keys.md``).
BALANCE_KEY = "skinslink:balance"
_TTL_SECONDS = 3600


class BalanceClient(Protocol):
    """What the balance read needs from Skinslink."""

    async def balance(self) -> Balance:
        """``GET /merchant/balance``."""
        ...


async def refresh_balance(
    redis: Redis, client: BalanceClient, *, settings: Settings
) -> Balance | None:
    """Read the balance, cache it and export it; ``None`` (nothing changed) on a failure."""
    try:
        answer = await client.balance()
    except (SkinslinkError, SkinslinkUnavailableError) as exc:
        log.warning("skinslink.balance.failed", error=type(exc).__name__)
        return None
    set_skinslink_balance(
        float(answer.available), float(answer.hold), float(settings.skinslink_balance_alert_usd)
    )
    try:
        value = {
            "available": str(answer.available),
            "hold": str(answer.hold),
            "read_at": now().isoformat(),
        }
        await redis.set(BALANCE_KEY, json.dumps(value), ex=_TTL_SECONDS)
    except RedisError as exc:
        log.warning("skinslink.balance.cache_failed", error=type(exc).__name__)
    return answer


async def cached_balance(
    redis: Redis,
) -> tuple[Decimal | None, Decimal | None, datetime | None]:
    """``(available, hold, read_at)`` of the last good read; all ``None`` when unknown."""
    with contextlib.suppress(RedisError, ValueError, KeyError, TypeError, InvalidOperation):
        raw = await redis.get(BALANCE_KEY)
        if raw is not None:
            data = json.loads(raw)
            return (
                Decimal(data["available"]),
                Decimal(data["hold"]),
                datetime.fromisoformat(data["read_at"]),
            )
    return None, None, None


__all__ = ["BALANCE_KEY", "BalanceClient", "cached_balance", "refresh_balance"]
