"""Trade link: parse, ownership, verdict mapping, cache, breaker (spec §7.2)."""

from __future__ import annotations

import fakeredis.aioredis
import pytest
from csmarket.core.errors import ValidationError
from csmarket.modules.users.tradelink import (
    CheckResult,
    assert_owned,
    check_trade_link,
    parse_tradelink,
)

OWNER = "76561198000000001"  # partner 39734273
#: A redrawn fake link — never a real partner/token in tests.
LINK = "https://steamcommunity.com/tradeoffer/new/?partner=39734273&token=AbCdEf12"


class _Wax:
    def __init__(self, info: str | None = None, exc: Exception | None = None) -> None:
        self.info, self.exc, self.calls = info, exc, 0

    async def check_tradelink(self, url: str) -> str | None:
        self.calls += 1
        if self.exc:
            raise self.exc
        return self.info


class _Hold:
    def __init__(self, days: int | None = 0) -> None:
        self.days, self.calls = days, 0

    async def trade_hold_days(self, steam_id: str, token: str) -> int | None:
        self.calls += 1
        return self.days


@pytest.fixture
def redis():
    return fakeredis.aioredis.FakeRedis(decode_responses=True)


def test_parse_accepts_steams_own_link_and_trims() -> None:
    link = parse_tradelink(f"  {LINK} ")
    assert (link.partner, link.token, link.steam_id) == (39734273, "AbCdEf12", OWNER)
    assert link.url == LINK


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "https://steamcommunity.com/tradeoffer/new/?partner=39734273",
        "http://steamcommunity.com/tradeoffer/new/?partner=39734273&token=AbCdEf12",
        "https://steamcommunity.com.evil/tradeoffer/new/?partner=39734273&token=AbCdEf12",
        "https://steamcommunity.com/tradeoffer/new/?partner=abc&token=AbCdEf12",
    ],
)
def test_parse_rejects_anything_else(raw: str) -> None:
    with pytest.raises(ValidationError) as exc:
        parse_tradelink(raw)
    assert exc.value.extra["code"] == "trade_link_invalid"


_NEW = "https://steamcommunity.com/tradeoffer/new/?"


@pytest.mark.parametrize(
    "raw",
    [
        # Arabic-Indic and full-width digits are \d in a Unicode regex, and int() accepts
        # them: a look-alike link would turn into somebody's partner id.
        f"{_NEW}partner=\u0663\u0669\u0667\u0663\u0664&token=AbCdEf12",
        f"{_NEW}partner=\uff13\uff19\uff17\uff13&token=AbCdEf12",
        # Cyrillic and accented letters are \w in a Unicode regex.
        f"{_NEW}partner=39734273&token=\u0410bCdEf12",
        f"{_NEW}partner=39734273&token=AbC\u00e9Ef12",
    ],
)
def test_parse_rejects_non_ascii_look_alikes(raw: str) -> None:
    with pytest.raises(ValidationError) as exc:
        parse_tradelink(raw)
    assert exc.value.extra["code"] == "trade_link_invalid"


def test_ownership() -> None:
    assert_owned(parse_tradelink(LINK), OWNER)
    with pytest.raises(ValidationError) as exc:
        assert_owned(parse_tradelink(LINK), "76561198000000002")
    assert exc.value.extra["code"] == "trade_link_not_yours"


@pytest.mark.parametrize(
    ("info", "days", "expected"),
    [
        (None, 0, CheckResult(verdict="ok", reason=None)),
        (None, None, CheckResult(verdict="ok", reason=None)),  # no Steam number → Waxpeer alone
        (None, 7, CheckResult(verdict="warn", reason="hold")),
        ("Inventory is private", 0, CheckResult(verdict="bad", reason="private")),
        ("User has trade ban", 0, CheckResult(verdict="bad", reason="trade_ban")),
        ("Invalid tradelink", 0, CheckResult(verdict="bad", reason="invalid")),
    ],
)
async def test_verdict_mapping(redis, info, days, expected) -> None:
    result = await check_trade_link(
        parse_tradelink(LINK), waxpeer=_Wax(info), hold=_Hold(days), redis=redis
    )
    assert result == expected


async def test_bad_link_skips_the_hold_call(redis) -> None:
    hold = _Hold(7)
    await check_trade_link(parse_tradelink(LINK), waxpeer=_Wax("private"), hold=hold, redis=redis)
    assert hold.calls == 0


async def test_cached_for_ten_minutes_and_key_has_no_token(redis) -> None:
    wax = _Wax()
    for _ in range(2):
        await check_trade_link(parse_tradelink(LINK), waxpeer=wax, hold=_Hold(0), redis=redis)
    assert wax.calls == 1
    keys = [k async for k in redis.scan_iter("users:tradelink:*")]
    assert keys
    assert all("AbCdEf12" not in k and "39734273" not in k for k in keys)
    assert 590 <= await redis.ttl(keys[0]) <= 600


async def test_outage_is_unavailable_and_opens_the_breaker(redis) -> None:
    from csmarket.modules.skins.waxpeer import WaxpeerUnavailableError

    first = await check_trade_link(
        parse_tradelink(LINK),
        waxpeer=_Wax(exc=WaxpeerUnavailableError("x")),
        hold=_Hold(),
        redis=redis,
    )
    assert first == CheckResult(verdict=None, reason="unavailable")
    wax = _Wax()
    second = await check_trade_link(parse_tradelink(LINK), waxpeer=wax, hold=_Hold(), redis=redis)
    assert second == CheckResult(verdict=None, reason="unavailable")
    assert wax.calls == 0  # breaker open: no upstream call
    assert 50 <= await redis.ttl("users:tradelink:breaker") <= 60


async def test_unavailable_is_not_cached(redis) -> None:
    from csmarket.modules.skins.waxpeer import WaxpeerUnavailableError

    await check_trade_link(
        parse_tradelink(LINK),
        waxpeer=_Wax(exc=WaxpeerUnavailableError("x")),
        hold=_Hold(),
        redis=redis,
    )
    await redis.delete("users:tradelink:breaker")
    result = await check_trade_link(
        parse_tradelink(LINK), waxpeer=_Wax(), hold=_Hold(0), redis=redis
    )
    assert result.verdict == "ok"


async def test_malformed_waxpeer_answer_is_unavailable_not_bad(redis) -> None:
    import httpx
    import respx
    from csmarket.modules.skins.waxpeer import WaxpeerClient

    wax = WaxpeerClient(api_key="k", base_url="https://api.waxpeer.com/v1", timeout_seconds=1)
    with respx.mock() as mock:
        mock.post("https://api.waxpeer.com/v1/check-tradelink").mock(
            return_value=httpx.Response(200, json=[])
        )
        result = await check_trade_link(
            parse_tradelink(LINK), waxpeer=wax, hold=_Hold(), redis=redis
        )
    assert result == CheckResult(verdict=None, reason="unavailable")
    assert await redis.exists("users:tradelink:breaker")
    assert [
        k async for k in redis.scan_iter("users:tradelink:*") if k != "users:tradelink:breaker"
    ] == []
