"""The USD/UZS rate the catalogue prices with (ruling Q3).

Postgres (``fx_snapshots``) is the record; Redis ``fx:usd_uzs`` is a copy the request
path reads first. A Redis error is never fatal — the newest snapshot is one indexed
query away. A rate older than ``max_age_days`` is treated as no rate: the page then
shows dollars rather than soʻm at a week-old rate.

The snapshot is always the CBU's own rate. The buyer's rate — every soʻm price, the
catalogue's and checkout's alike — is that rate plus ``fx_uplift_pct`` (ADR-0011), applied
in :func:`current_usd_uzs` only; an order keeps the snapshot id and the uplift it used.
"""

from __future__ import annotations

import contextlib
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.clock import now
from csmarket.core.config import get_settings
from csmarket.core.ids import new_id
from csmarket.core.logging import get_logger
from csmarket.modules.fx.models import FxSnapshot

log = get_logger("csmarket.fx.service")

REDIS_KEY = "fx:usd_uzs"
_REDIS_TTL_SECONDS = 86_400
#: The buyer's rate is kept to the CBU's own precision (kopecks of a soʻm).
_RATE_PLACES = Decimal("0.01")
#: A refresh with an unchanged rate adds a row only when the newest is this old.
_REFRESH_ROW_AFTER = timedelta(hours=20)


@dataclass(frozen=True)
class UsdUzs:
    """A rate and the snapshot it came from.

    ``rate`` is what soʻm prices use: ``cbu_rate`` × (1 + ``uplift_pct`` / 100). Straight from
    a snapshot (``refresh_usd_uzs``) the two are equal and the uplift is 0.
    """

    rate: Decimal
    snapshot_id: str
    fetched_at: datetime
    source: str
    cbu_rate: Decimal = Decimal(0)
    uplift_pct: Decimal = Decimal(0)

    def uplifted(self, pct: Decimal) -> UsdUzs:
        """This snapshot's rate with ``pct`` percent added."""
        rate = (self.cbu_rate * (1 + pct / 100)).quantize(_RATE_PLACES, rounding=ROUND_HALF_UP)
        return replace(self, rate=rate, uplift_pct=pct)


def _of(row: FxSnapshot) -> UsdUzs:
    return UsdUzs(
        rate=row.usd_uzs,
        snapshot_id=row.id,
        fetched_at=row.fetched_at,
        source=row.source,
        cbu_rate=row.usd_uzs,
    )


async def _cache(redis: Redis, value: UsdUzs) -> None:
    payload = json.dumps(
        {
            "rate": str(value.rate),
            "snapshot_id": value.snapshot_id,
            "fetched_at": value.fetched_at.isoformat(),
            "source": value.source,
        }
    )
    with contextlib.suppress(RedisError):
        await redis.set(REDIS_KEY, payload, ex=_REDIS_TTL_SECONDS)


async def _latest(db: AsyncSession) -> FxSnapshot | None:
    return (
        await db.execute(select(FxSnapshot).order_by(FxSnapshot.fetched_at.desc()).limit(1))
    ).scalar_one_or_none()


async def record_snapshot(db: AsyncSession, *, rate: Decimal, source: str) -> FxSnapshot:
    """Insert one snapshot (flush only — the caller commits).

    ``fetched_at`` comes from ``core.clock`` rather than the server default, so a clock
    override reaches it.
    """
    row = FxSnapshot(id=new_id(), usd_uzs=rate, source=source, fetched_at=now())
    db.add(row)
    await db.flush()
    return row


async def current_usd_uzs(
    db: AsyncSession,
    redis: Redis,
    *,
    max_age_days: int,
    uplift_pct: Decimal | None = None,
) -> UsdUzs | None:
    """The buyer's rate from the newest snapshot younger than ``max_age_days``, or ``None``.

    Args:
        db: Session (read only).
        redis: The ``fx:usd_uzs`` copy, read first.
        max_age_days: Older snapshots count as no rate.
        uplift_pct: Percent added to the CBU rate; ``settings.fx_uplift_pct`` when omitted.
    """
    pct = get_settings().fx_uplift_pct if uplift_pct is None else uplift_pct
    raw = await _current(db, redis, max_age_days=max_age_days)
    return None if raw is None else raw.uplifted(pct)


async def _current(db: AsyncSession, redis: Redis, *, max_age_days: int) -> UsdUzs | None:
    """The newest snapshot younger than ``max_age_days`` (the CBU rate), or ``None``."""
    oldest = now() - timedelta(days=max_age_days)
    with contextlib.suppress(RedisError, ValueError, KeyError, TypeError, InvalidOperation):
        raw = await redis.get(REDIS_KEY)
        if raw is not None:
            data = json.loads(raw)
            cached = UsdUzs(
                rate=Decimal(data["rate"]),
                snapshot_id=str(data["snapshot_id"]),
                fetched_at=datetime.fromisoformat(data["fetched_at"]),
                source=str(data["source"]),
                cbu_rate=Decimal(data["rate"]),
            )
            if cached.fetched_at >= oldest:
                return cached
    row = await _latest(db)
    if row is None or row.fetched_at < oldest:
        return None
    value = _of(row)
    await _cache(redis, value)
    return value


async def refresh_usd_uzs(
    db: AsyncSession,
    redis: Redis,
    *,
    fetch: Callable[[], Awaitable[Decimal]],
    source: str = "cbu",
) -> UsdUzs:
    """Fetch, record when new (or the newest row is ≥ 20 h old), **commit**, then cache.

    It commits itself so Redis never points at a snapshot a rollback erased; only the
    scheduler job and the dev seed call it.
    """
    rate = await fetch()
    latest = await _latest(db)
    if (
        latest is not None
        and latest.usd_uzs == rate
        and now() - latest.fetched_at < _REFRESH_ROW_AFTER
    ):
        value = _of(latest)
    else:
        value = _of(await record_snapshot(db, rate=rate, source=source))
        log.info("fx.snapshot.recorded", rate=str(rate), source=source)
    await db.commit()
    await _cache(redis, value)
    return value
