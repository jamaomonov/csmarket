"""Repricing is serialised and cheap.

Two writers reprice the whole catalogue: the price tick and an admin replacing
the rules. Interleaved, the tick could write prices from the rules it read a
moment before the admin's commit, and they stay wrong until the next tick. Both
take one transaction-scoped advisory lock first, and the tick reads the rules
from Postgres under it — Redis is published only after the admin's commit.
"""

from __future__ import annotations

from collections.abc import Iterator

import fakeredis.aioredis
import pytest
from csmarket.core.ids import new_id
from csmarket.modules.skins.models import SkinItem
from csmarket.modules.skins.prices import sync_prices
from csmarket.modules.skins.pricing import DEFAULT_RULES
from csmarket.modules.skins.repricing import reprice_rows
from csmarket.modules.skins.settings import publish_rules
from csmarket.modules.skins.waxpeer import SnapshotRow
from sqlalchemy import event, select
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

pytestmark = pytest.mark.asyncio


@pytest.fixture
def sql() -> Iterator[list[str]]:
    seen: list[str] = []

    def record(_c: object, _cur: object, statement: str, *_a: object) -> None:
        seen.append(statement)

    event.listen(Engine, "before_cursor_execute", record)
    yield seen
    event.remove(Engine, "before_cursor_execute", record)


def _first(seen: list[str], needle: str) -> int:
    hits = [i for i, s in enumerate(seen) if needle in s]
    assert hits, f"no statement containing {needle!r}"
    return hits[0]


def _row(name: str, *, active: bool = True) -> SkinItem:
    return SkinItem(
        id=new_id(),
        market_hash_name=name,
        phase="",
        slug=name.lower().replace(" ", "-").replace("|", "").replace("(", "").replace(")", ""),
        category="pistols",
        search_text=name.lower(),
        min_auto_units=1000,
        count_auto=10,
        active=active,
        cheapest_auto=[{"listing_id": 1, "price_units": 1000}],
    )


class _Client:
    def __init__(self, rows: list[SnapshotRow]) -> None:
        self.rows = rows

    async def iter_snapshot_rows(self, *, game: str = "csgo"):  # type: ignore[no-untyped-def]
        for row in self.rows:
            yield row

    async def prices(self, *, game: str = "csgo") -> list[dict[str, object]]:
        return []


async def test_reprice_reads_only_the_pricing_columns(
    db_session: AsyncSession, sql: list[str]
) -> None:
    db_session.add(_row("P250 | Sand (Field-Tested)"))
    await db_session.commit()
    sql.clear()
    await reprice_rows(db_session, DEFAULT_RULES)
    selects = [s for s in sql if s.lstrip().upper().startswith("SELECT")]
    assert selects
    assert not any("cheapest_auto" in s or "search_text" in s for s in selects)


async def test_reprice_clears_a_deactivated_rows_price(db_session: AsyncSession) -> None:
    row = _row("P250 | Sand (Field-Tested)")
    db_session.add(row)
    await db_session.commit()
    await reprice_rows(db_session, DEFAULT_RULES)
    row.active = False
    await db_session.commit()
    await reprice_rows(db_session, DEFAULT_RULES)
    await db_session.commit()
    stored = (
        await db_session.execute(select(SkinItem.sell_price_usd, SkinItem.discount_percent))
    ).one()
    assert tuple(stored) == (None, None)


async def test_the_price_tick_locks_then_reads_rules_from_postgres(
    db_engine,
    sql: list[str],  # type: ignore[no-untyped-def]
) -> None:
    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    # A stale document in Redis must not be what the tick prices from.
    await publish_rules(DEFAULT_RULES)
    rows = [SnapshotRow(1, "P250 | Sand (Field-Tested)", 1000, True)]
    await sync_prices(factory, _Client(rows), redis)  # type: ignore[arg-type]
    lock = _first(sql, "pg_advisory_xact_lock")
    assert lock < _first(sql, "FROM skin_pricing_rules")
    assert lock < _first(sql, "UPDATE skin_items")
    await redis.aclose()
