"""The catalogue cache version (an integer every cached page key carries).

Kept apart from ``prices`` so the read path (``service``, ``routes``) never imports the
Waxpeer client. Any write that changes what a visitor sees — a price tick, hiding an
item, an alias edit — bumps it after its commit, and every cached page expires at once.
"""

from __future__ import annotations

import contextlib

from redis.asyncio import Redis
from redis.exceptions import RedisError

CATALOG_VERSION_KEY = "skins:catalog:ver"


async def catalog_version(redis: Redis) -> int:
    """The current version; 0 when Redis is unreadable (pages then just miss the cache)."""
    with contextlib.suppress(RedisError, ValueError, TypeError):
        raw = await redis.get(CATALOG_VERSION_KEY)
        return int(raw) if raw is not None else 0
    return 0


async def bump_catalog_version(redis: Redis) -> None:
    """+1; a Redis error is swallowed (the 60 s page TTL bounds staleness anyway)."""
    with contextlib.suppress(RedisError):
        await redis.incr(CATALOG_VERSION_KEY)
