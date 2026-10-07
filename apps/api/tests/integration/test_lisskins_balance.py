"""The LIS-SKINS balance: cached for the dashboard, exported as gauges; a failed read keeps
the last good copy."""

from __future__ import annotations

from decimal import Decimal

from csmarket.core.config import get_settings
from csmarket.core.redis import get_redis
from csmarket.modules.lisskins.api import Balance, LisskinsUnavailableError
from csmarket.modules.lisskins.balance import cached_balance, refresh_balance
from prometheus_client import REGISTRY


class _Client:
    def __init__(self, answer: Balance | Exception) -> None:
        self.answer = answer

    async def balance(self) -> Balance:
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


async def test_unknown_before_any_read() -> None:
    assert await cached_balance(get_redis()) == (None, None, None)


async def test_refresh_caches_and_exports() -> None:
    settings = get_settings().model_copy(update={"lisskins_balance_alert_usd": Decimal(50)})
    answer = Balance(available=Decimal("99.96"), locked=Decimal("1.5"), protected=Decimal(0))
    assert await refresh_balance(get_redis(), _Client(answer), settings=settings) == answer
    available, locked, read_at = await cached_balance(get_redis())
    assert (available, locked) == (Decimal("99.96"), Decimal("1.5"))
    assert read_at is not None
    assert REGISTRY.get_sample_value("csmarket_lisskins_balance_available_usd") == 99.96
    assert REGISTRY.get_sample_value("csmarket_lisskins_balance_threshold_usd") == 50.0


async def test_a_failed_read_keeps_the_cache() -> None:
    settings = get_settings()
    one = Balance(available=Decimal(1), locked=Decimal(0), protected=Decimal(0))
    await refresh_balance(get_redis(), _Client(one), settings=settings)
    assert (
        await refresh_balance(
            get_redis(), _Client(LisskinsUnavailableError("x")), settings=settings
        )
        is None
    )
    assert (await cached_balance(get_redis()))[0] == Decimal(1)
