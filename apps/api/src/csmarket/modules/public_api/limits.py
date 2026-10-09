"""Per-key request limits of the public API (fixed one-minute windows in Redis).

A key's own ``*_per_min`` column beats the default in :data:`LIMITS`; ``NULL`` = the default.
"""

from __future__ import annotations

from typing import Literal

from csmarket.core.errors import RateLimitedError
from csmarket.modules.auth.api import hit_counter
from csmarket.modules.public_api.auth import ApiCaller
from csmarket.modules.public_api.models import ApiKey

Bucket = Literal["read", "order", "feed", "check"]

#: Hits allowed per minute when the key sets none.
LIMITS: dict[Bucket, int] = {"read": 60, "order": 10, "feed": 1, "check": 30}
#: The ``api_keys`` column that overrides each bucket.
LIMIT_COLUMNS: dict[Bucket, str] = {
    "read": "read_per_min",
    "order": "orders_per_min",
    "feed": "feed_per_min",
    "check": "check_per_min",
}
WINDOW_SECONDS = 60


def limit_for(key: ApiKey, bucket: Bucket) -> int:
    """The key's own limit for ``bucket``, else the default."""
    own: int | None = getattr(key, LIMIT_COLUMNS[bucket])
    return LIMITS[bucket] if own is None else own


def effective_limits(key: ApiKey) -> dict[Bucket, int]:
    """Every bucket's limit as the key enforces it."""
    return {bucket: limit_for(key, bucket) for bucket in LIMITS}


async def enforce(caller: ApiCaller, bucket: Bucket) -> None:
    """Count one hit on the key's ``bucket``.

    Raises:
        RateLimitedError: ``rate_limited`` over the limit; carries ``Retry-After``.
    """
    over = await hit_counter(
        f"public_api:rl:{bucket}:{caller.key.id}",
        limit=limit_for(caller.key, bucket),
        window=WINDOW_SECONDS,
    )
    if over:
        raise RateLimitedError("too many requests", code="rate_limited", retry_after=WINDOW_SECONDS)


__all__ = [
    "LIMITS",
    "LIMIT_COLUMNS",
    "WINDOW_SECONDS",
    "Bucket",
    "effective_limits",
    "enforce",
    "limit_for",
]
