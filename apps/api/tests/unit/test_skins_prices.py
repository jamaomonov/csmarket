"""Snapshot rows fold into one aggregate per canonical (name, phase)."""

from __future__ import annotations

from csmarket.modules.skins.prices import aggregate, price_hash
from csmarket.modules.skins.waxpeer import SnapshotRow


def _rows() -> list[SnapshotRow]:
    return [
        SnapshotRow(1, "AK-47 | Redline (Field-Tested)", 27867, True),
        SnapshotRow(2, "AK-47 | Redline (Field-Tested)", 27878, True),
        SnapshotRow(3, "AK-47 | Redline (Field-Tested)", 27000, False),
        SnapshotRow(4, "★ Karambit | Doppler Phase 2 (Factory New)", 1450000, True),
        SnapshotRow(5, "AWP | Manual Only (Field-Tested)", 5000, False),
    ]


def test_manual_listings_count_but_never_price() -> None:
    agg = aggregate(_rows())
    ak = agg[("AK-47 | Redline (Field-Tested)", "")]
    assert (ak.min_auto, ak.count_auto) == (27867, 2)
    assert (ak.min_all, ak.count_all) == (27000, 3)
    assert ak.cheapest == [(1, 27867), (2, 27878)]


def test_a_manual_only_name_has_no_auto_price() -> None:
    awp = aggregate(_rows())[("AWP | Manual Only (Field-Tested)", "")]
    assert (awp.min_auto, awp.count_auto, awp.cheapest) == (None, 0, [])
    assert (awp.min_all, awp.count_all) == (5000, 1)


def test_inline_phase_is_the_aggregate_key() -> None:
    assert ("★ Karambit | Doppler (Factory New)", "Phase 2") in aggregate(_rows())


def test_cheapest_is_capped_at_ten_and_sorted() -> None:
    rows = [SnapshotRow(i, "P250 | Sand Dune (Field-Tested)", 1000 - i, True) for i in range(15)]
    agg = aggregate(rows)[("P250 | Sand Dune (Field-Tested)", "")]
    assert len(agg.cheapest) == 10
    assert agg.cheapest[0] == (14, 986)
    assert [p for _, p in agg.cheapest] == sorted(p for _, p in agg.cheapest)


def test_hash_changes_with_prices_only() -> None:
    a = aggregate(_rows())[("AK-47 | Redline (Field-Tested)", "")]
    b = aggregate(_rows())[("AK-47 | Redline (Field-Tested)", "")]
    assert price_hash(a) == price_hash(b)
    b.min_auto = 27866
    assert price_hash(a) != price_hash(b)


async def test_catalog_version_is_zero_when_redis_is_down() -> None:
    from csmarket.modules.skins.cachekeys import bump_catalog_version, catalog_version
    from redis.exceptions import ConnectionError as RedisConnectionError

    class Down:
        async def get(self, *_: object) -> None:
            raise RedisConnectionError("down")

        async def incr(self, *_: object) -> None:
            raise RedisConnectionError("down")

    assert await catalog_version(Down()) == 0  # type: ignore[arg-type]
    await bump_catalog_version(Down())  # type: ignore[arg-type]  # no raise
