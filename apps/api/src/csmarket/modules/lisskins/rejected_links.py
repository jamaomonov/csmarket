"""Trade links LIS-SKINS refused (``invalid_trade_url`` and its kin), remembered for a day.

A buyer's link that LIS-SKINS refuses is refused for every lot, while Steam, Waxpeer and
Skinslink take it (a partner's orders of 2026-10-09). Remembering it lets the partner API say so
before the next payment: ``POST /public/tradelink/check`` answers ``rejected_by_market`` and
``POST /public/orders`` stops buying LIS-SKINS lots for it. Keyed by a SHA-256 of the link —
the link's token is PII and never stored. Redis errors are swallowed: this is advisory.
"""

from __future__ import annotations

import contextlib
import hashlib

from redis.asyncio import Redis
from redis.exceptions import RedisError

#: A day: long enough to spare the buyer a row of refunds, short enough to forgive a fix.
REJECTED_TTL = 24 * 3600


def _key(link: str) -> str:
    return "lisskins:link_rejected:" + hashlib.sha256(link.encode()).hexdigest()


async def remember_rejection(redis: Redis, link: str) -> None:
    """LIS-SKINS refused ``link`` (the canonical trade-link URL)."""
    with contextlib.suppress(RedisError):
        await redis.set(_key(link), "1", ex=REJECTED_TTL)


async def is_rejected(redis: Redis, link: str) -> bool:
    """Whether LIS-SKINS refused ``link`` within the last day."""
    with contextlib.suppress(RedisError):
        return bool(await redis.exists(_key(link)))
    return False


__all__ = ["REJECTED_TTL", "is_rejected", "remember_rejection"]
