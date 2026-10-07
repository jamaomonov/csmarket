"""The checkout's live look at a LIS-SKINS lot: budget, breaker, the three verdicts."""

from __future__ import annotations

from decimal import Decimal

import pytest
from csmarket.core.redis import get_redis
from csmarket.modules.lisskins import availability
from csmarket.modules.lisskins.api import (
    Availability,
    LisskinsError,
    LisskinsRateLimitedError,
    live_price,
    recheck_chosen,
)
from csmarket.modules.skins.api import Offer

from tests.integration.fake_lisskins_client import FakeAvailability

AVAILABLE = Availability(available={5: Decimal("9.00")}, unavailable=frozenset())


def _offer(offer_id: str, source: str, units: int) -> Offer:
    return Offer(
        offer_id=offer_id,
        source=source,  # type: ignore[arg-type]  # the test's literal
        price_units=units,
        float_value=None,
        paint_seed=None,
    )


async def test_the_three_verdicts() -> None:
    redis = get_redis()
    assert await live_price(redis, FakeAvailability(AVAILABLE), 5) == ("available", 9_000)
    gone = Availability(available={}, unavailable=frozenset({5}))
    assert await live_price(redis, FakeAvailability(gone), 5) == ("gone", None)
    neither = Availability(available={}, unavailable=frozenset())
    assert await live_price(redis, FakeAvailability(neither), 5) == ("unknown", None)


async def test_a_spent_budget_answers_unknown_without_a_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(availability, "BUDGET_PER_MINUTE", 1)
    fake = FakeAvailability(AVAILABLE)
    assert await live_price(get_redis(), fake, 5) == ("available", 9_000)
    assert await live_price(get_redis(), fake, 5) == ("unknown", None)
    assert len(fake.calls) == 1


async def test_an_outage_opens_the_breaker_and_a_refusal_does_not() -> None:
    redis = get_redis()
    refused = FakeAvailability(LisskinsError("bad", status=422, code="invalid_ids_value"))
    assert await live_price(redis, refused, 5) == ("unknown", None)
    assert not await redis.exists(availability.BREAKER_KEY)
    limited = FakeAvailability(LisskinsRateLimitedError("slow down", retry_after=3))
    assert await live_price(redis, limited, 5) == ("unknown", None)
    assert await redis.exists(availability.BREAKER_KEY)
    later = FakeAvailability(AVAILABLE)
    assert await live_price(redis, later, 5) == ("unknown", None)
    assert later.calls == []


async def test_recheck_touches_only_the_chosen_lisskins_offer() -> None:
    offers = [_offer("sl:1", "skinslink", 8_000), _offer("ls:5", "lisskins", 8_500)]
    fake = FakeAvailability(AVAILABLE)
    same = await recheck_chosen(offers, "sl:1", redis=get_redis(), client=fake)
    assert same == offers
    assert fake.calls == []
    moved = await recheck_chosen(offers, "ls:5", redis=get_redis(), client=fake)
    assert [(o.offer_id, o.price_units) for o in moved] == [("sl:1", 8_000), ("ls:5", 9_000)]
    gone = FakeAvailability(Availability(available={}, unavailable=frozenset({5})))
    dropped = await recheck_chosen(offers, "ls:5", redis=get_redis(), client=gone)
    assert [o.offer_id for o in dropped] == ["sl:1"]
