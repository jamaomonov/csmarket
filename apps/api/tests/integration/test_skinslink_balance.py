"""``skinslink.balance``: one read of ``GET /merchant/balance`` cached for the dashboard and
exported as gauges; a failed read keeps the last good copy."""

from __future__ import annotations

from decimal import Decimal

import pytest
from csmarket.core.config import get_settings
from csmarket.core.redis import get_redis
from csmarket.modules.skinslink.api import Balance, SkinslinkUnavailableError
from csmarket.modules.skinslink.balance import cached_balance, refresh_balance
from prometheus_client import REGISTRY

pytestmark = pytest.mark.asyncio


class _Client:
    def __init__(self, answer: Balance | Exception) -> None:
        self.answer = answer

    async def balance(self) -> Balance:
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


async def test_nothing_cached_before_a_read() -> None:
    assert await cached_balance(get_redis()) == (None, None, None)


async def test_a_read_is_cached_and_exported() -> None:
    settings = get_settings().model_copy(update={"skinslink_balance_alert_usd": Decimal(50)})
    answer = Balance(total=Decimal("12.5"), hold=Decimal(2), available=Decimal("10.5"))
    assert await refresh_balance(get_redis(), _Client(answer), settings=settings) == answer
    available, hold, read_at = await cached_balance(get_redis())
    assert (available, hold) == (Decimal("10.5"), Decimal(2))
    assert read_at is not None
    sample = REGISTRY.get_sample_value
    assert sample("csmarket_skinslink_balance_available_usd") == 10.5
    assert sample("csmarket_skinslink_balance_hold_usd") == 2.0
    assert sample("csmarket_skinslink_balance_threshold_usd") == 50.0


async def test_a_failed_read_keeps_the_last_good_copy_and_stamp() -> None:
    settings = get_settings()
    one = Balance(total=Decimal(1), hold=Decimal(0), available=Decimal(1))
    await refresh_balance(get_redis(), _Client(one), settings=settings)
    stamp = REGISTRY.get_sample_value("csmarket_skinslink_balance_read_timestamp_seconds")
    failed = _Client(SkinslinkUnavailableError("x"))
    assert await refresh_balance(get_redis(), failed, settings=settings) is None
    assert (await cached_balance(get_redis()))[0] == Decimal(1)
    after = REGISTRY.get_sample_value("csmarket_skinslink_balance_read_timestamp_seconds")
    assert after == stamp


async def test_a_garbled_cache_reads_as_unknown() -> None:
    await get_redis().set("skinslink:balance", "not json")
    assert await cached_balance(get_redis()) == (None, None, None)
