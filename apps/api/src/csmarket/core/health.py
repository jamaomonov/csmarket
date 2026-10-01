"""Dependency checks behind ``/readyz``.

``/healthz`` says the process is alive; ``/readyz`` says it can do work. The
deploy workflow polls ``/readyz`` before calling a release good, so a stub that
always answers ``ready`` would wave a deploy through with Postgres down. Each
check is bounded: a wedged dependency must read as *failed*, not hang the probe
(and with it the Docker health check) indefinitely.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from sqlalchemy import text

from csmarket.core.db import get_engine
from csmarket.core.redis import get_redis

#: Per-check budget. Both dependencies are on the same box; a second is already long.
CHECK_TIMEOUT_SECONDS: float = 2.0


@dataclass(frozen=True, slots=True)
class Readiness:
    """The probe's answer: overall verdict plus one word per dependency."""

    ok: bool
    checks: dict[str, str]


async def check_postgres() -> bool:
    """``SELECT 1`` on a fresh connection from the shared engine."""
    async with get_engine().connect() as conn:
        await conn.execute(text("SELECT 1"))
    return True


async def check_redis() -> bool:
    """``PING`` on the shared client."""
    return bool(await get_redis().ping())


async def _guarded(check: Callable[[], Awaitable[bool]]) -> bool:
    """Run one check under the timeout; any exception or timeout is ``False``."""
    try:
        return bool(await asyncio.wait_for(check(), timeout=CHECK_TIMEOUT_SECONDS))
    except Exception:  # noqa: BLE001 -- a probe reports, it never raises
        return False


async def readiness() -> Readiness:
    """Run every dependency check concurrently and fold the results."""
    names = ("postgres", "redis")
    # Looked up at call time, not bound at import, so tests can monkeypatch them.
    results = await asyncio.gather(_guarded(check_postgres), _guarded(check_redis))
    checks = {
        name: ("ok" if passed else "fail") for name, passed in zip(names, results, strict=True)
    }
    return Readiness(ok=all(results), checks=checks)


__all__ = ["CHECK_TIMEOUT_SECONDS", "Readiness", "check_postgres", "check_redis", "readiness"]
