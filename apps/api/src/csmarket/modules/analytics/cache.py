"""Answers kept in Redis: 2 minutes, an hour once the window has settled (``Window.ttl``).

Keys: ``csmarket:analytics:v1:<endpoint>:<since>:<until>:<channel>``
(``docs/architecture/cache-keys.md``). Nothing invalidates them: a short TTL for a live
window, and a settled one cannot change.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from pydantic import BaseModel
from redis.asyncio import Redis

from csmarket.modules.analytics.window import Channel, Window

PREFIX = "csmarket:analytics:v1"


def cache_key(endpoint: str, w: Window, channel: Channel) -> str:
    """The Redis key of one answer."""
    return f"{PREFIX}:{endpoint}:{w.since.isoformat()}:{w.until.isoformat()}:{channel}"


async def cached[T: BaseModel](
    redis: Redis, key: str, ttl: int, model: type[T], build: Callable[[], Awaitable[T]]
) -> T:
    """``build()``'s answer, kept ``ttl`` seconds under ``key``."""
    hit = await redis.get(key)
    if hit is not None:
        return model.model_validate_json(hit)
    value = await build()
    await redis.set(key, value.model_dump_json(), ex=ttl)
    return value


__all__ = ["PREFIX", "cache_key", "cached"]
