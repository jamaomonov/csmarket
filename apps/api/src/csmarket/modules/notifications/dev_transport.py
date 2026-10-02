"""The dev transport (M4b ruling R6): letters go to Redis, never to a mailbox.

The last 50 rendered letters live under ``notifications:dev:mail`` for an hour; the dev-only
route ``GET /api/v1/dev/emails`` hands a signed-in user their own (e2e reads the
verification link there). The address is not stored: a letter is filed by its owner's id.
"""

from __future__ import annotations

import json
from typing import Any

from redis.asyncio import Redis

from csmarket.core import clock

#: Redis list of the latest dev letters, newest first.
DEV_MAIL_KEY = "notifications:dev:mail"
_KEEP = 50
_TTL_SECONDS = 3600


class DevTransport:
    """Stores each letter in Redis instead of sending it."""

    def __init__(self, redis: Redis) -> None:
        """Bind the Redis client the letters are written to."""
        self._redis = redis

    async def send(
        self,
        *,
        to: str,  # noqa: ARG002 -- never stored: the letter is filed by its owner
        subject: str,
        html: str,
        text: str,
        idempotency_key: str,
        user_id: str = "",
        kind: str = "",
    ) -> str:
        """Keep the letter; return a fake provider id derived from the idempotency key."""
        letter = {
            "to_user": user_id,
            "kind": kind,
            "subject": subject,
            "text": text,
            "html": html,
            "at": clock.now().isoformat(),
        }
        async with self._redis.pipeline(transaction=True) as pipe:
            pipe.lpush(DEV_MAIL_KEY, json.dumps(letter, ensure_ascii=False))
            pipe.ltrim(DEV_MAIL_KEY, 0, _KEEP - 1)
            pipe.expire(DEV_MAIL_KEY, _TTL_SECONDS)
            await pipe.execute()
        return f"dev-{idempotency_key}"[:64]

    # Any: letters are the JSON objects ``send`` stored.
    async def letters(self, *, user_id: str, kind: str | None = None) -> list[dict[str, Any]]:
        """The stored letters of ``user_id`` (optionally of one ``kind``), newest first."""
        raw = await self._redis.lrange(DEV_MAIL_KEY, 0, -1)
        found = [json.loads(item) for item in raw]
        return [
            m for m in found if m.get("to_user") == user_id and (kind is None or m["kind"] == kind)
        ]
