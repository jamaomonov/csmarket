"""LIS-SKINS refused a buyer's trade link: remembered by the link's hash for a day, so the
partner hears it before the next payment (YuPay's brief, 2026-10-10)."""

from __future__ import annotations

import pytest
from csmarket.core.redis import get_redis
from csmarket.modules.lisskins.rejected_links import (
    REJECTED_TTL,
    is_rejected,
    remember_rejection,
)

pytestmark = pytest.mark.asyncio

LINK = "https://steamcommunity.com/tradeoffer/new/?partner=1234567890&token=FAKEFAKE"


async def test_a_rejected_link_is_remembered_by_its_hash_for_a_day() -> None:
    redis = get_redis()
    assert not await is_rejected(redis, LINK)
    await remember_rejection(redis, LINK)
    assert await is_rejected(redis, LINK)
    keys = [k async for k in redis.scan_iter("lisskins:link_rejected:*")]
    assert len(keys) == 1
    assert "FAKEFAKE" not in str(keys[0])  # the token is PII: only a hash is stored
    assert 0 < await redis.ttl(keys[0]) <= REJECTED_TTL
    other = LINK.replace("FAKEFAKE", "OTHERTOK")
    assert not await is_rejected(redis, other)
