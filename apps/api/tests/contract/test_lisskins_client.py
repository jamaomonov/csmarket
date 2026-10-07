"""LIS-SKINS API (respx): balance, buy, info, check-availability, every refusal code.

Shapes from the OpenAPI export of https://lis-skins.stoplight.io (2026-10-07). Every
partner, token, Steam id and skin id is made up.
"""

from __future__ import annotations

import json
from decimal import Decimal

import httpx
import pytest
import respx
from csmarket.modules.lisskins.api import (
    LisskinsClient,
    LisskinsError,
    LisskinsForbiddenError,
    LisskinsRateLimitedError,
    LisskinsUnavailableError,
    Purchase,
)

BASE = "https://api.lis-skins.com/v1"
SKIN = {
    "id": 125345,
    "name": "M4A4 | Spider Lily (Field-Tested)",
    "price": 2.03,
    "status": "processing",
    "return_reason": None,
    "return_charged_commission": None,
    "error": None,
    "steam_trade_offer_id": None,
    "steam_trade_offer_created_at": None,
    "steam_trade_offer_expiry_at": None,
    "steam_trade_offer_finished_at": None,
}
PURCHASE = {
    "purchase_id": 55,
    "steam_id": "76561190000000001",
    "created_at": "2026-10-07T14:50:08.000000Z",
    "custom_id": "order-1",
    "skins": [SKIN],
}


def _client() -> LisskinsClient:
    return LisskinsClient(api_key="k", base_url=BASE, timeout_seconds=1)


async def _buy(max_price: str = "2.03") -> Purchase:
    return await _client().buy(
        skin_id=125345,
        partner=39734273,
        token="AbCdEf12",
        max_price_usd=Decimal(max_price),
        custom_id="order-1",
    )


@respx.mock
async def test_balance_sends_the_bearer_key_and_parses() -> None:
    route = respx.get(f"{BASE}/user/balance").mock(
        return_value=httpx.Response(
            200,
            json={"data": {"balance": 99.96, "balance_locked": 1.5, "trade_protection_balance": 0}},
        )
    )
    b = await _client().balance()
    assert route.calls.last.request.headers["Authorization"] == "Bearer k"
    assert (b.available, b.locked, b.protected) == (Decimal("99.96"), Decimal("1.5"), Decimal(0))


@respx.mock
@pytest.mark.parametrize(("cap", "sent"), [("2.03", 2.03), ("12.349", 12.34), ("12.345", 12.34)])
async def test_buy_posts_one_id_and_a_cap_never_above_ours(cap: str, sent: float) -> None:
    route = respx.post(f"{BASE}/market/buy").mock(
        return_value=httpx.Response(200, json={"data": PURCHASE})
    )
    await _buy(cap)
    body = json.loads(route.calls.last.request.read())
    assert body == {
        "ids": [125345],
        "partner": "39734273",
        "token": "AbCdEf12",
        "max_price": sent,
        "custom_id": "order-1",
    }


@respx.mock
async def test_buy_parses_the_purchase_and_never_keeps_the_steam_id() -> None:
    respx.post(f"{BASE}/market/buy").mock(return_value=httpx.Response(200, json={"data": PURCHASE}))
    p = await _buy()
    assert (p.purchase_id, p.custom_id) == (55, "order-1")
    skin = p.skin
    assert (skin.id, skin.status, skin.price_usd) == (125345, "processing", Decimal("2.03"))
    assert "76561190000000001" not in repr(p)


@respx.mock
@pytest.mark.parametrize(
    "code",
    [
        "custom_id_already_exists",
        "skins_price_higher_than_max_price",
        "insufficient_funds",
        "invalid_trade_url",
        "user_trade_ban",
        "user_cant_trade",
        "private_inventory",
        "too_many_failed_attempts_for_user",
    ],
)
async def test_every_buy_refusal_carries_its_code(code: str) -> None:
    respx.post(f"{BASE}/market/buy").mock(return_value=httpx.Response(400, json={"error": code}))
    with pytest.raises(LisskinsError) as exc:
        await _buy()
    assert (exc.value.status, exc.value.code) == (400, code)
    assert not isinstance(exc.value, LisskinsForbiddenError)


@respx.mock
async def test_skins_unavailable_names_the_ids() -> None:
    respx.post(f"{BASE}/market/buy").mock(
        return_value=httpx.Response(
            400, json={"error": "skins_unavailable", "unavailable_ids": [125345]}
        )
    )
    with pytest.raises(LisskinsError) as exc:
        await _buy()
    assert (exc.value.code, exc.value.unavailable_ids) == ("skins_unavailable", (125345,))


@respx.mock
async def test_a_validation_error_is_a_refusal_with_its_code() -> None:
    respx.post(f"{BASE}/market/buy").mock(
        return_value=httpx.Response(422, json={"error": "invalid_partner_value"})
    )
    with pytest.raises(LisskinsError) as exc:
        await _buy()
    assert (exc.value.status, exc.value.code) == (422, "invalid_partner_value")


@respx.mock
@pytest.mark.parametrize(
    ("status", "error"),
    [
        (401, LisskinsForbiddenError),
        (403, LisskinsForbiddenError),
        (408, LisskinsUnavailableError),
        (500, LisskinsUnavailableError),
        (502, LisskinsUnavailableError),
        (503, LisskinsUnavailableError),
        (504, LisskinsUnavailableError),
    ],
)
async def test_http_statuses_map_to_errors(status: int, error: type[Exception]) -> None:
    respx.get(f"{BASE}/user/balance").mock(return_value=httpx.Response(status, json={}))
    with pytest.raises(error):
        await _client().balance()


@respx.mock
async def test_429_carries_retry_after() -> None:
    respx.post(f"{BASE}/market/buy").mock(
        return_value=httpx.Response(429, headers={"Retry-After": "7"}, json={})
    )
    with pytest.raises(LisskinsRateLimitedError) as exc:
        await _buy()
    assert exc.value.retry_after == 7.0


@respx.mock
@pytest.mark.parametrize(
    "answer",
    [
        httpx.Response(200, text="<html>"),
        httpx.Response(200, json={"data": {"purchase_id": 55, "skins": []}}),
        httpx.Response(200, json={"nothing": 1}),
    ],
)
async def test_an_unreadable_buy_answer_is_unavailable(answer: httpx.Response) -> None:
    respx.post(f"{BASE}/market/buy").mock(return_value=answer)
    with pytest.raises(LisskinsUnavailableError):
        await _buy()


@respx.mock
async def test_a_transport_failure_is_unavailable() -> None:
    respx.post(f"{BASE}/market/buy").mock(side_effect=httpx.ReadTimeout("slow"))
    with pytest.raises(LisskinsUnavailableError):
        await _buy()


@respx.mock
async def test_info_asks_by_custom_ids_and_skips_an_unreadable_entry() -> None:
    returned = {**SKIN, "status": "return", "return_reason": "trade_timeout"}
    route = respx.get(f"{BASE}/market/info").mock(
        return_value=httpx.Response(
            200, json={"data": [{**PURCHASE, "skins": [returned]}, {"purchase_id": "x"}]}
        )
    )
    found = await _client().info(custom_ids=["order-1", "order-2"])
    assert route.calls.last.request.url.params.get_list("custom_ids[]") == ["order-1", "order-2"]
    assert [(p.custom_id, p.skin.status, p.skin.return_reason) for p in found] == [
        ("order-1", "return", "trade_timeout")
    ]


async def test_info_refuses_more_than_200_ids_and_asks_nothing_for_none() -> None:
    with pytest.raises(ValueError, match="200"):
        await _client().info(custom_ids=[str(n) for n in range(201)])
    assert await _client().info(custom_ids=[]) == []


@respx.mock
async def test_check_availability_reads_prices_and_gone_ids() -> None:
    route = respx.get(f"{BASE}/market/check-availability").mock(
        return_value=httpx.Response(
            200,
            json={"data": {"available_skins": {"125345": 2.03}, "unavailable_skin_ids": [7]}},
        )
    )
    a = await _client().check_availability([125345, 7])
    assert route.calls.last.request.url.params.get_list("ids[]") == ["125345", "7"]
    assert (a.available, a.unavailable) == ({125345: Decimal("2.03")}, frozenset({7}))


@respx.mock
async def test_an_empty_available_list_reads_as_none_available() -> None:
    """PHP encodes an empty map as ``[]``."""
    respx.get(f"{BASE}/market/check-availability").mock(
        return_value=httpx.Response(
            200, json={"data": {"available_skins": [], "unavailable_skin_ids": [7]}}
        )
    )
    a = await _client().check_availability([7])
    assert (a.available, a.unavailable) == ({}, frozenset({7}))


async def test_no_key_is_unavailable_without_a_call() -> None:
    with pytest.raises(LisskinsUnavailableError):
        await LisskinsClient(api_key="", base_url=BASE, timeout_seconds=1).balance()
