"""Waxpeer purchase side: ``buy-one-p2p``, ``check-many-project-id``, ``user`` (respx).

Shapes recorded from real purchases on 2026-09-28 (spec §8.1). Every trade link, partner,
token, Steam ID and seller below is redrawn — never a real one in tests.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import httpx
import pytest
import respx
from csmarket.core import metrics
from csmarket.core.config import get_settings
from csmarket.modules.skins.api import (
    TradeClient,
    WaxpeerBuyRefusedError,
    WaxpeerError,
    WaxpeerForbiddenError,
    WaxpeerRateLimitedError,
    WaxpeerSeller,
    WaxpeerTradeClient,
    WaxpeerUnavailableError,
    trade_client,
)

BASE = "https://api.waxpeer.com/v1"
PARTNER = 39734273
TOKEN = "AbCdEf12"


def _client(key: str = "k") -> WaxpeerTradeClient:
    return WaxpeerTradeClient(api_key=key, base_url=BASE, timeout_seconds=1)


async def _buy(price_units: int = 1000, client: WaxpeerTradeClient | None = None) -> object:
    return await (client or _client()).buy_one_p2p(
        item_id=1, price_units=price_units, partner=PARTNER, token=TOKEN, project_id="o-1"
    )


def _trade(**over: object) -> dict[str, object]:
    base: dict[str, object] = {
        "id": 30717201,
        "name": "Galil AR | Grey Smoke (Field-Tested)",
        "status": 4,
        "project_id": "o-1",
        "custom_id": "c1",
        "trade_id": "9393511289",
        "done": False,
        "for_steamid64": "76561190000000001",
        "reason": None,
        "release_date": None,
        "is_released": False,
        "seller_name": "seller-one",
        "seller_avatar": "https://avatars.example.test/x_medium.jpg",
        "seller_steam_joined": 1730230098,
        "seller_steam_level": 12,
        "price": 6,
        "send_until": "1790636153",
        "last_updated": "1790634353",
        "counter": "564",
    }
    return {**base, **over}


def _calls(endpoint: str, outcome: str) -> float:
    series = metrics.WAXPEER_CALLS.labels(endpoint=endpoint, outcome=outcome)
    return series._value.get()  # type: ignore[no-any-return]


# --- buy-one-p2p -----------------------------------------------------------------------


@respx.mock
async def test_buying_one_listing_returns_waxpeers_id() -> None:
    route = respx.get(f"{BASE}/buy-one-p2p").respond(
        200, json={"success": True, "id": 30717149, "price": 5}
    )
    before = _calls("buy", "ok")
    bought = await _client().buy_one_p2p(
        item_id=53860909078, price_units=5, partner=PARTNER, token=TOKEN, project_id="o-1"
    )
    assert (bought.id, bought.price_units) == (30717149, 5)
    params = route.calls.last.request.url.params
    assert (params["api"], params["item_id"], params["price"], params["project_id"]) == (
        "k",
        "53860909078",
        "5",
        "o-1",
    )
    assert (params["partner"], params["token"]) == (str(PARTNER), TOKEN)
    assert _calls("buy", "ok") == before + 1


@respx.mock
async def test_buy_refusal_carries_new_price() -> None:
    respx.get(f"{BASE}/buy-one-p2p").respond(
        200, json={"success": False, "msg": "Price changed", "new_price": 9}
    )
    before = _calls("buy", "refused")
    with pytest.raises(WaxpeerBuyRefusedError) as err:
        await _buy(price_units=5)
    assert err.value.new_price_units == 9
    assert err.value.status == 200
    assert "Price changed" in str(err.value)
    assert _calls("buy", "refused") == before + 1


@respx.mock
async def test_buy_refusal_without_a_new_price() -> None:
    respx.get(f"{BASE}/buy-one-p2p").respond(200, json={"success": False, "msg": "Item sold"})
    with pytest.raises(WaxpeerBuyRefusedError) as err:
        await _buy()
    assert err.value.new_price_units is None
    assert '"Item sold"' in err.value.body


@pytest.mark.parametrize("raw", ["nine", None, True, 9.5, [9]])
@respx.mock
async def test_buy_refusal_with_an_unreadable_new_price(raw: object) -> None:
    respx.get(f"{BASE}/buy-one-p2p").respond(
        200, json={"success": False, "msg": "Price changed", "new_price": raw}
    )
    with pytest.raises(WaxpeerBuyRefusedError) as err:
        await _buy()
    assert err.value.new_price_units is None


@respx.mock
async def test_buy_refusal_accepts_a_numeric_string_price() -> None:
    respx.get(f"{BASE}/buy-one-p2p").respond(
        200, json={"success": False, "msg": "Price changed", "new_price": "12"}
    )
    with pytest.raises(WaxpeerBuyRefusedError) as err:
        await _buy()
    assert err.value.new_price_units == 12


@respx.mock
async def test_buy_403_is_forbidden_not_a_refusal() -> None:
    respx.get(f"{BASE}/buy-one-p2p").respond(403, text="You need to whitelist your IP")
    before = _calls("buy", "forbidden")
    with pytest.raises(WaxpeerForbiddenError) as err:
        await _buy()
    assert not isinstance(err.value, WaxpeerBuyRefusedError)
    assert err.value.status == 403
    assert _calls("buy", "forbidden") == before + 1


@respx.mock
async def test_buy_429_is_rate_limited() -> None:
    respx.get(f"{BASE}/buy-one-p2p").respond(429, headers={"Retry-After": "2"})
    before = _calls("buy", "rate_limited")
    with pytest.raises(WaxpeerRateLimitedError) as err:
        await _buy()
    assert err.value.retry_after_seconds == 2.0
    assert _calls("buy", "rate_limited") == before + 1


@respx.mock
async def test_buy_5xx_is_an_error_with_its_status() -> None:
    respx.get(f"{BASE}/buy-one-p2p").respond(502, text="bad gateway")
    before = _calls("buy", "error")
    with pytest.raises(WaxpeerError) as err:
        await _buy()
    assert type(err.value) is WaxpeerError
    assert err.value.status == 502
    assert _calls("buy", "error") == before + 1


@respx.mock
async def test_buy_network_failure_is_unavailable() -> None:
    respx.get(f"{BASE}/buy-one-p2p").mock(side_effect=httpx.ReadTimeout("t"))
    before = _calls("buy", "unavailable")
    with pytest.raises(WaxpeerUnavailableError):
        await _buy()
    assert _calls("buy", "unavailable") == before + 1


@respx.mock
async def test_buy_unreadable_200_is_unavailable() -> None:
    respx.get(f"{BASE}/buy-one-p2p").respond(200, text="<html>challenge</html>")
    with pytest.raises(WaxpeerUnavailableError):
        await _buy()


@pytest.mark.parametrize(
    "body",
    [{"success": True}, {"success": True, "id": "x", "price": 5}, {"success": True, "id": 7}],
)
@respx.mock
async def test_buy_success_without_an_id_or_price_is_unavailable(body: dict[str, object]) -> None:
    # The buy may have happened: the caller resolves it by lookup, never by buying again.
    respx.get(f"{BASE}/buy-one-p2p").respond(200, json=body)
    with pytest.raises(WaxpeerUnavailableError):
        await _buy()


async def test_buy_without_a_key_is_unavailable_without_traffic() -> None:
    with pytest.raises(WaxpeerUnavailableError):
        await _buy(client=_client(""))


@respx.mock
async def test_no_url_or_body_is_logged(
    caplog: pytest.LogCaptureFixture, capsys: pytest.CaptureFixture[str]
) -> None:
    respx.get(f"{BASE}/buy-one-p2p").respond(500, text="boom token=AbCdEf12")
    with pytest.raises(WaxpeerError):
        await _buy(price_units=5)
    respx.get(f"{BASE}/check-many-project-id").mock(side_effect=httpx.ConnectError("x"))
    with pytest.raises(WaxpeerUnavailableError):
        await _client().check_project_ids(["o-1"])
    out = capsys.readouterr()
    logged = caplog.text + out.out + out.err
    assert "skins.waxpeer.call" in logged
    for leak in (TOKEN, "api=", str(PARTNER), "boom", "https://"):
        assert leak not in logged, leak


# --- check-many-project-id --------------------------------------------------------------


@respx.mock
async def test_trades_are_read_by_project_id() -> None:
    route = respx.get(f"{BASE}/check-many-project-id").respond(
        200,
        json={
            "success": True,
            "trades": [
                _trade(),
                _trade(project_id="o-2", release_date="2026-10-05T16:00:00.000Z"),
                _trade(project_id="o-3", status=6, done=True, reason="Buyer failed to accept"),
            ],
        },
    )
    before = _calls("lookup", "ok")
    trades = await _client().check_project_ids(["o-1", "o-2", "o-3"])
    assert route.calls.last.request.url.params.get_list("id") == ["o-1", "o-2", "o-3"]
    sent, accepted, failed = trades
    assert (sent.status, sent.release_date, sent.trade_id) == (4, None, "9393511289")
    assert sent.send_until == datetime.fromtimestamp(1790636153, tz=UTC)
    assert accepted.release_date == datetime(2026, 10, 5, 16, tzinfo=UTC)
    assert (failed.status, failed.done, failed.reason) == (6, True, "Buyer failed to accept")
    assert sent.seller == WaxpeerSeller(
        name="seller-one",
        avatar_url="https://avatars.example.test/x_medium.jpg",
        level=12,
        joined_at=datetime(2024, 10, 29, 19, 28, 18, tzinfo=UTC),
    )
    assert _calls("lookup", "ok") == before + 1


@respx.mock
async def test_lookup_sends_repeated_ids_and_drops_the_buyer_steam_id() -> None:
    route = respx.get(f"{BASE}/check-many-project-id").respond(
        200,
        json={"success": True, "trades": [_trade(status=4, for_steamid64="76561190000000000")]},
    )
    trades = await _client().check_project_ids(["o-1", "o-2"])
    assert route.calls.last.request.url.params.get_list("id") == ["o-1", "o-2"]
    dumped = trades[0].model_dump()
    assert "for_steamid64" not in dumped
    assert "76561190000000000" not in repr(trades[0])


@respx.mock
async def test_a_key_waxpeer_has_never_seen_is_an_empty_list_not_an_error() -> None:
    respx.get(f"{BASE}/check-many-project-id").respond(200, json={"success": True, "trades": []})
    assert await _client().check_project_ids(["never-seen"]) == []


@respx.mock
async def test_lookup_with_an_unreadable_entry_is_unavailable() -> None:
    # A trade we cannot read must not be read as "absent" (and so "never bought").
    respx.get(f"{BASE}/check-many-project-id").respond(
        200, json={"success": True, "trades": ["x", _trade()]}
    )
    with pytest.raises(WaxpeerUnavailableError):
        await _client().check_project_ids(["o-1"])


@respx.mock
async def test_lookup_without_a_trades_list_is_unavailable() -> None:
    # Not "unknown ids": an answer we cannot read must never look like "never bought".
    respx.get(f"{BASE}/check-many-project-id").respond(200, json={"success": True})
    before = _calls("lookup", "unavailable")
    with pytest.raises(WaxpeerUnavailableError):
        await _client().check_project_ids(["o-1"])
    assert _calls("lookup", "unavailable") == before + 1


async def test_an_empty_lookup_makes_no_call() -> None:
    with respx.mock(assert_all_called=False) as mock:
        route = mock.get(f"{BASE}/check-many-project-id")
        assert await _client().check_project_ids([]) == []
        assert not route.called


async def test_more_than_100_ids_is_refused_not_truncated() -> None:
    # A silently dropped id would read as "never bought" and invite a second buy.
    with pytest.raises(ValueError, match="100"):
        await _client().check_project_ids([f"o-{n}" for n in range(101)])


async def test_one_bare_string_is_refused() -> None:
    with pytest.raises(TypeError, match="sequence"):
        await _client().check_project_ids("o-1")


@respx.mock
async def test_exactly_100_ids_go_in_one_call() -> None:
    ids = [f"o-{n}" for n in range(100)]
    route = respx.get(f"{BASE}/check-many-project-id").respond(
        200, json={"success": True, "trades": []}
    )
    assert await _client().check_project_ids(ids) == []
    assert route.calls.last.request.url.params.get_list("id") == ids


@respx.mock
async def test_lookup_refusal_is_a_waxpeer_error() -> None:
    respx.get(f"{BASE}/check-many-project-id").respond(
        200, json={"success": False, "msg": "bad id"}
    )
    before = _calls("lookup", "refused")
    with pytest.raises(WaxpeerError) as err:
        await _client().check_project_ids(["o-1"])
    assert err.value.status == 200
    assert _calls("lookup", "refused") == before + 1


@respx.mock
async def test_lookup_403_is_forbidden() -> None:
    respx.get(f"{BASE}/check-many-project-id").respond(403, text="whitelist")
    with pytest.raises(WaxpeerForbiddenError):
        await _client().check_project_ids(["o-1"])


@respx.mock
async def test_lookup_429_is_rate_limited() -> None:
    respx.get(f"{BASE}/check-many-project-id").respond(429, json={"msBeforeNext": 1500})
    with pytest.raises(WaxpeerRateLimitedError) as err:
        await _client().check_project_ids(["o-1"])
    assert err.value.retry_after_seconds == 1.5


# --- user (balance) ---------------------------------------------------------------------


@respx.mock
async def test_balance_units_reads_user_wallet() -> None:
    respx.get(f"{BASE}/user").respond(200, json={"success": True, "user": {"wallet": 53300}})
    before = _calls("balance", "ok")
    assert await _client().balance_units() == 53300
    assert _calls("balance", "ok") == before + 1


@pytest.mark.parametrize(
    "body",
    [
        {"success": True},
        {"success": True, "user": "x"},
        {"success": True, "user": {"wallet": "53300"}},
        {"success": True, "user": {"wallet": True}},
        {"success": True, "user": {"wallet": 1.5}},
    ],
)
@respx.mock
async def test_balance_without_a_numeric_wallet_is_unavailable(body: dict[str, object]) -> None:
    respx.get(f"{BASE}/user").respond(200, json=body)
    with pytest.raises(WaxpeerUnavailableError):
        await _client().balance_units()


@respx.mock
async def test_balance_5xx_is_an_error() -> None:
    respx.get(f"{BASE}/user").respond(503, text="down")
    before = _calls("balance", "error")
    with pytest.raises(WaxpeerError) as err:
        await _client().balance_units()
    assert err.value.status == 503
    assert _calls("balance", "error") == before + 1


# --- wiring ------------------------------------------------------------------------------


async def test_unavailable_is_not_a_waxpeer_error() -> None:
    # Task 8 orders its ``except`` clauses on this: unavailable is its own branch.
    assert not issubclass(WaxpeerUnavailableError, WaxpeerError)
    assert issubclass(WaxpeerRateLimitedError, WaxpeerUnavailableError)
    assert issubclass(WaxpeerForbiddenError, WaxpeerError)
    assert issubclass(WaxpeerBuyRefusedError, WaxpeerError)


def test_trade_client_uses_the_buy_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CSMARKET_WAXPEER_API_KEY", "k2")
    monkeypatch.setenv("CSMARKET_WAXPEER_BUY_TIMEOUT_SECONDS", "7.5")
    get_settings.cache_clear()
    try:
        client = trade_client()
    finally:
        get_settings.cache_clear()
    assert isinstance(client, WaxpeerTradeClient)
    assert isinstance(client, TradeClient)
    assert client._timeout == 7.5
    assert client._api_key == "k2"


@pytest.mark.parametrize(
    "entry",
    [
        {"project_id": ""},
        {"project_id": None},
        {"id": 0},
        {"id": "x"},
        {"id": -3},
    ],
)
@respx.mock
async def test_lookup_entry_without_an_id_or_project_id_is_unavailable(
    entry: dict[str, object],
) -> None:
    # An entry we cannot tie to an order must never make that order look "never bought".
    respx.get(f"{BASE}/check-many-project-id").respond(
        200, json={"success": True, "trades": [_trade(project_id="o-2"), _trade(**entry)]}
    )
    before = _calls("lookup", "unavailable")
    with pytest.raises(WaxpeerUnavailableError):
        await _client().check_project_ids(["o-1", "o-2"])
    assert _calls("lookup", "unavailable") == before + 1


@respx.mock
async def test_a_cancelled_call_is_not_counted() -> None:
    def _cancel(_: httpx.Request) -> httpx.Response:
        raise asyncio.CancelledError

    respx.get(f"{BASE}/buy-one-p2p").mock(side_effect=_cancel)
    before = {o: _calls("buy", o) for o in ("error", "unavailable", "ok")}
    with pytest.raises(asyncio.CancelledError):
        await _buy()
    assert {o: _calls("buy", o) for o in before} == before
