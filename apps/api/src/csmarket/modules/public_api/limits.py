"""Per-key request limits of the public API (fixed one-minute windows in Redis)."""

from __future__ import annotations

from typing import Literal

from csmarket.core.errors import RateLimitedError
from csmarket.modules.auth.api import hit_counter
from csmarket.modules.public_api.auth import ApiCaller

Bucket = Literal["read", "order", "feed"]

#: Hits allowed per minute.
LIMITS: dict[Bucket, int] = {"read": 60, "order": 10, "feed": 1}
WINDOW_SECONDS = 60


async def enforce(caller: ApiCaller, bucket: Bucket) -> None:
    """Count one hit on the key's ``bucket``.

    Raises:
        RateLimitedError: ``rate_limited`` over the limit; carries ``Retry-After``.
    """
    over = await hit_counter(
        f"public_api:rl:{bucket}:{caller.key.id}", limit=LIMITS[bucket], window=WINDOW_SECONDS
    )
    if over:
        raise RateLimitedError("too many requests", code="rate_limited", retry_after=WINDOW_SECONDS)


__all__ = ["LIMITS", "WINDOW_SECONDS", "Bucket", "enforce"]
