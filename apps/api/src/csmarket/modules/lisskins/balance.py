"""The LIS-SKINS balance (spec 2026-10-07 §7): read every 5 minutes by the
``lisskins.balance`` job, cached for the admin dashboard and exported as gauges
(``LisskinsBalanceLow``). A failed read keeps the last good copy and stamp."""

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
from csmarket.core.metrics import set_lisskins_balance
from csmarket.modules.lisskins.client import Balance, LisskinsError, LisskinsUnavailableError

log = get_logger("csmarket.lisskins.balance")

#: The last good balance read (``docs/architecture/cache-keys.md``).
BALANCE_KEY = "lisskins:balance"
_TTL_SECONDS = 3600


class BalanceClient(Protocol):
    """What the balance read needs from LIS-SKINS."""

    async def balance(self) -> Balance:
        """``GET /user/balance``."""
        ...


async def refresh_balance(
    redis: Redis, client: BalanceClient, *, settings: Settings
) -> Balance | None:
    """Read the balance, cache it and export it; ``None`` (nothing changed) on a failure."""
    try:
        answer = await client.balance()
    except (LisskinsError, LisskinsUnavailableError) as exc:
        log.warning("lisskins.balance.failed", error=type(exc).__name__)
        return None
    set_lisskins_balance(
        float(answer.available), float(answer.locked), float(settings.lisskins_balance_alert_usd)
    )
    try:
        value = {
            "available": str(answer.available),
            "locked": str(answer.locked),
            "read_at": now().isoformat(),
        }
        await redis.set(BALANCE_KEY, json.dumps(value), ex=_TTL_SECONDS)
    except RedisError as exc:
        log.warning("lisskins.balance.cache_failed", error=type(exc).__name__)
    return answer


async def cached_balance(redis: Redis) -> tuple[Decimal | None, Decimal | None, datetime | None]:
    """``(available, locked, read_at)`` of the last good read; all ``None`` when unknown."""
    with contextlib.suppress(RedisError, ValueError, KeyError, TypeError, InvalidOperation):
        raw = await redis.get(BALANCE_KEY)
        if raw is not None:
            data = json.loads(raw)
            return (
                Decimal(data["available"]),
                Decimal(data["locked"]),
                datetime.fromisoformat(data["read_at"]),
            )
    return None, None, None


__all__ = ["BALANCE_KEY", "BalanceClient", "cached_balance", "refresh_balance"]
