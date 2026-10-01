"""Last outcome of the catalogue jobs, for the admin status card (ruling Q6).

Written by the scheduler after every run, read by ``GET /admin/skins/catalog/status``.
Redis only, no TTL: losing it to a flush costs a status line until the next run.
"""

from __future__ import annotations

import contextlib
import json
from dataclasses import dataclass
from datetime import datetime

from redis.asyncio import Redis
from redis.exceptions import RedisError

from csmarket.core.clock import now

JOB_IMPORT = "import"
JOB_PRICE_SYNC = "price_sync"


def _key(job: str) -> str:
    return f"skins:job:{job}"


@dataclass(frozen=True)
class JobStatus:
    """One run's outcome. ``error`` is our own short label, never upstream text."""

    finished_at: datetime
    ok: bool
    counters: dict[str, int]
    error: str | None


async def record_job(
    redis: Redis, job: str, *, ok: bool, counters: dict[str, int], error: str | None = None
) -> None:
    """Store the outcome; a Redis error is swallowed (status is advisory)."""
    payload = json.dumps(
        {"finished_at": now().isoformat(), "ok": ok, "counters": counters, "error": error}
    )
    with contextlib.suppress(RedisError):
        await redis.set(_key(job), payload)


async def read_job(redis: Redis, job: str) -> JobStatus | None:
    """The last outcome, or ``None`` when unknown or unreadable."""
    with contextlib.suppress(RedisError, ValueError, KeyError, TypeError):
        raw = await redis.get(_key(job))
        if raw is None:
            return None
        data = json.loads(raw)
        return JobStatus(
            finished_at=datetime.fromisoformat(data["finished_at"]),
            ok=bool(data["ok"]),
            counters={str(k): int(v) for k, v in dict(data["counters"]).items()},
            error=None if data["error"] is None else str(data["error"]),
        )
    return None


__all__ = ["JOB_IMPORT", "JOB_PRICE_SYNC", "JobStatus", "read_job", "record_job"]
